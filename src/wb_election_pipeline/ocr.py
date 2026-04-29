from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import asyncio
import json
import os
from typing import Iterable
import re

import pdfplumber
import requests

from .env import load_dotenv, numbered_env_values

NUTRIENT_OCR_URL = "https://api.nutrient.io/processor/ocr"


@dataclass(frozen=True)
class OcrCredential:
    provider: str
    env_name: str
    value: str


@dataclass(frozen=True)
class OcrResult:
    source_pdf: Path
    provider: str
    credential_name: str
    text_path: Path | None = None
    searchable_pdf_path: Path | None = None


class OcrProviderError(RuntimeError):
    pass


def discover_credentials(providers: Iterable[str]) -> list[OcrCredential]:
    load_dotenv()
    credentials: list[OcrCredential] = []
    provider_set = {provider.lower() for provider in providers}

    if "llamacloud" in provider_set:
        for name, value in numbered_env_values("LLAMA_CLOUD_API_KEY"):
            credentials.append(OcrCredential("llamacloud", name, value))

    if "nutrient" in provider_set:
        for name, value in os.environ.items():
            upper = name.upper()
            if upper.startswith("NUTRIENT_") and "KEY" in upper and value:
                credentials.append(OcrCredential("nutrient", name, value))

    if "markitdown" in provider_set:
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            credentials.append(OcrCredential("markitdown", "OPENAI_API_KEY", openai_key))
        else:
            credentials.append(OcrCredential("markitdown", "NO_LLM_CLIENT", ""))

    if "glm_ocr" in provider_set:
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.environ.get("GLM_OCR_MODEL", "glm-ocr:latest")
        credentials.append(OcrCredential("glm_ocr", "OLLAMA_LOCAL", f"{base_url}|{model}"))

    if "gemini_ocr" in provider_set:
        for name, value in numbered_env_values("GEMINI_API_KEY"):
            model = os.environ.get("GEMINI_OCR_MODEL", "gemini-2.5-flash")
            credentials.append(OcrCredential("gemini_ocr", name, f"{value}|{model}"))

    return credentials


def extract_text_from_pdf(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n\n".join(page.extract_text() or "" for page in pdf.pages)


async def _llamacloud_parse_async(pdf_path: Path, api_key: str) -> str:
    try:
        from llama_cloud_services import LlamaParse

        parser = LlamaParse(
            api_key=api_key,
            result_type="markdown",
            high_res_ocr=True,
            aggressive_table_extraction=True,
            language="en",
            verbose=False,
        )
        parsed = await parser.aparse(str(pdf_path))
        if isinstance(parsed, str):
            return parsed
        documents = await parser.aload_data(str(pdf_path))
        return "\n\n".join(getattr(doc, "text", str(doc)) for doc in documents)
    except ImportError:
        pass

    try:
        from llama_cloud import AsyncLlamaCloud  # type: ignore[attr-defined]
    except ImportError as exc:
        raise OcrProviderError(
            "LlamaCloud SDK is not installed. Run: python -m pip install llama-cloud-services llama-cloud"
        ) from exc
    except Exception as exc:
        raise OcrProviderError(f"LlamaCloud SDK import failed: {exc}") from exc

    client = AsyncLlamaCloud(api_key=api_key)
    uploaded = await client.files.create(file=str(pdf_path), purpose="parse")
    parsed = await client.parsing.parse(
        file_id=uploaded.id,
        tier="agentic",
        version="latest",
        expand=["markdown", "text"],
    )
    markdown = getattr(parsed, "markdown", None)
    text = getattr(parsed, "text", None)
    if markdown:
        return str(markdown)
    if text:
        return str(text)
    if hasattr(parsed, "model_dump_json"):
        return parsed.model_dump_json(indent=2)
    return str(parsed)


def run_llamacloud(pdf_path: Path, out_dir: Path, credential: OcrCredential) -> OcrResult:
    text = asyncio.run(_llamacloud_parse_async(pdf_path, credential.value))
    text_dir = out_dir / "llamacloud_markdown"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / f"{pdf_path.stem}.md"
    text_path.write_text(text, encoding="utf-8")
    return OcrResult(pdf_path, "llamacloud", credential.env_name, text_path=text_path)


def run_nutrient(pdf_path: Path, out_dir: Path, credential: OcrCredential, language: str = "english") -> OcrResult:
    pdf_dir = out_dir / "nutrient_searchable_pdfs"
    text_dir = out_dir / "nutrient_text"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    target_pdf = pdf_dir / pdf_path.name
    headers = {"Authorization": f"Bearer {credential.value}"}
    data = {"language": language}
    with pdf_path.open("rb") as handle:
        response = requests.post(
            NUTRIENT_OCR_URL,
            headers=headers,
            files={"file": (pdf_path.name, handle, "application/pdf")},
            data={"data": json.dumps(data)},
            timeout=180,
        )
    if response.status_code in {401, 402, 403, 408, 409, 422, 429, 500, 502, 503, 504}:
        raise OcrProviderError(f"Nutrient OCR failed with HTTP {response.status_code}: {response.text[:300]}")
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise OcrProviderError(f"Nutrient OCR did not return a PDF: {response.headers.get('content-type')}")
    target_pdf.write_bytes(response.content)
    text_path = text_dir / f"{pdf_path.stem}.txt"
    text_path.write_text(extract_text_from_pdf(target_pdf), encoding="utf-8")
    return OcrResult(
        pdf_path,
        "nutrient",
        credential.env_name,
        text_path=text_path,
        searchable_pdf_path=target_pdf,
    )


def run_glm_ocr(pdf_path: Path, out_dir: Path, credential: OcrCredential) -> OcrResult:
    """Run OCR using a local Ollama vision model (e.g. glm-ocr:latest)."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise OcrProviderError(
            "PyMuPDF is not installed. Run: python -m pip install pymupdf"
        ) from exc
    import base64
    from io import BytesIO

    from PIL import Image

    base_url, model = credential.value.split("|", 1)
    chat_url = f"{base_url.rstrip('/')}/api/chat"
    dpi = int(os.environ.get("GLM_OCR_DPI", "96"))
    max_side = int(os.environ.get("GLM_OCR_MAX_SIDE", "1280"))

    doc = fitz.open(str(pdf_path))
    page_texts: list[str] = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        image = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
        if max(image.size) > max_side:
            ratio = max_side / max(image.size)
            new_size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        img_bytes = buffer.getvalue()
        img_b64 = base64.b64encode(img_bytes).decode("ascii")
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": "Please perform OCR on this image and return the exact text content, preserving table structure with spaces or pipes. Output only the extracted text, no commentary.",
                    "images": [img_b64],
                }
            ],
            "stream": False,
        }
        resp = requests.post(chat_url, json=payload, timeout=300)
        if not resp.ok:
            raise OcrProviderError(
                f"Ollama API error {resp.status_code} for page {page.number}: {resp.text[:300]}"
            )
        data = resp.json()
        text = data.get("message", {}).get("content", "")
        page_texts.append(text)
    doc.close()

    full_text = "\n\n".join(page_texts)
    if not full_text.strip():
        raise OcrProviderError("glm_ocr returned empty text for all pages")

    text_dir = out_dir / "glm_ocr_markdown"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / f"{pdf_path.stem}.md"
    text_path.write_text(full_text, encoding="utf-8")
    return OcrResult(pdf_path, "glm_ocr", credential.env_name, text_path=text_path)


def _gemini_prompt() -> str:
    custom_prompt = os.environ.get("GEMINI_OCR_PROMPT")
    if custom_prompt:
        return custom_prompt

    task = os.environ.get("GEMINI_OCR_TASK", "form20").strip().lower()
    if task in {"roll", "voter_roll", "voter-roll", "electoral_roll", "electoral-roll"}:
        return (
            "This is a scanned page from a Bengali Indian electoral voter roll. "
            "Extract the voter table exactly as it appears, using one markdown table. "
            "Use these columns in this order when visible: serial_no, part_no, name, relation_type, "
            "relative_name, gender, age, epic_optional. Preserve Bengali names and labels exactly as Unicode. "
            "Do not translate, infer, correct spellings, summarize, skip rows, or add commentary. "
            "Leave missing cells blank."
        )

    return (
        "This is a scanned page from an Indian election Form 20 (Final Result Sheet). "
        "The page contains a wide table where the first few columns are: "
        "Serial No., Polling Station (booth number), then one column per candidate with their vote totals, "
        "then Total Valid Votes, Rejected Votes, NOTA, Total Votes Cast. "
        "The candidate names appear as column headers spanning the top of the table. "
        "Extract the FULL table exactly, preserving the candidate name headers and all booth-level vote numbers. "
        "Output as a markdown table. If candidate names span multiple rows at the top, include all of them. "
        "Do not skip any rows or columns. Output only the markdown table, no commentary."
    )


def run_gemini_ocr(pdf_path: Path, out_dir: Path, credentials: "list[OcrCredential] | OcrCredential") -> OcrResult:
    """Run OCR using Google Gemini Vision API on each PDF page, rotating credentials per page."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise OcrProviderError(
            "PyMuPDF is not installed. Run: python -m pip install pymupdf"
        ) from exc
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as exc:
        raise OcrProviderError(
            "google-genai is not installed. Run: python -m pip install google-genai"
        ) from exc

    cred_list: list[OcrCredential] = (
        credentials if isinstance(credentials, list) else [credentials]
    )

    prompt = _gemini_prompt()

    doc = fitz.open(str(pdf_path))
    page_texts: list[str] = []
    text_dir = out_dir / "gemini_ocr_markdown"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / f"{pdf_path.stem}.md"
    for i, page in enumerate(doc):
        page_rotation = page.rotation
        if page_rotation != 0:
            # Render ignoring the metadata rotation (raw scan orientation),
            # then re-rotate with PIL to get the correct upright image.
            # For 270° pages the raw scan is flipped; rotating the raw 90° CW fixes it.
            try:
                from PIL import Image
                import io as _io
                pix = page.get_pixmap(dpi=200, annots=False)
                # temporarily clear rotation so get_pixmap returns the raw scan
                page.set_rotation(0)
                pix_raw = page.get_pixmap(dpi=200, annots=False)
                page.set_rotation(page_rotation)  # restore
                raw_img = Image.open(_io.BytesIO(pix_raw.tobytes("png")))
                # 270° metadata → scan is 90° CCW relative to upright → rotate 90° CW
                rotation_fix = {90: 270, 180: 180, 270: 90}.get(page_rotation, 0)
                if rotation_fix:
                    raw_img = raw_img.rotate(-rotation_fix, expand=True)
                buf = _io.BytesIO()
                raw_img.save(buf, format="PNG")
                img_bytes = buf.getvalue()
            except Exception:
                pix = page.get_pixmap(dpi=200)
                img_bytes = pix.tobytes("png")
        else:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
        # Rotate through credentials round-robin per page
        ordered = [cred_list[(i + j) % len(cred_list)] for j in range(len(cred_list))]
        page_text: str | None = None
        last_exc: Exception | None = None
        for cred in ordered:
            api_key, model = cred.value.split("|", 1)
            client = genai.Client(api_key=api_key)
            for attempt in range(3):  # retry 503 transient errors up to 3 times
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=[
                            genai_types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                            prompt,
                        ],
                    )
                    page_text = response.text or ""
                    break
                except Exception as exc:
                    last_exc = exc
                    err_str = str(exc)
                    if "503" in err_str or "UNAVAILABLE" in err_str:
                        import time
                        time.sleep(5 * (attempt + 1))  # 5s, 10s, 15s
                        continue
                    break  # non-503 error (e.g. 429 quota) — try next key immediately
            if page_text is not None:
                break
        if page_text is None:
            raise OcrProviderError(f"All Gemini credentials failed for page {i + 1}: {last_exc}")
        page_texts.append(f"Page {i + 1}\n\n{page_text}")
        # Long roll PDFs can take many minutes. Checkpoint after every page so
        # a timeout or quota error does not discard completed pages.
        text_path.write_text("\n\n".join(page_texts), encoding="utf-8")
    doc.close()

    full_text = "\n\n".join(page_texts)
    if not full_text.strip():
        raise OcrProviderError("gemini_ocr returned empty text for all pages")

    text_path.write_text(full_text, encoding="utf-8")
    return OcrResult(pdf_path, "gemini_ocr", cred_list[0].env_name, text_path=text_path)


def run_markitdown(pdf_path: Path, out_dir: Path, credential: OcrCredential) -> OcrResult:
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise OcrProviderError(
            "markitdown is not installed. Run: python -m pip install 'markitdown[pdf]' markitdown-ocr"
        ) from exc

    kwargs: dict[str, object] = {}
    enable_plugins = False
    if credential.value:
        try:
            from openai import OpenAI

            kwargs["llm_client"] = OpenAI(api_key=credential.value)
            kwargs["llm_model"] = os.environ.get("MARKITDOWN_LLM_MODEL", "gpt-4o")
            enable_plugins = True
        except ImportError as exc:
            raise OcrProviderError("openai is required for MarkItDown OCR plugin mode") from exc

    converter = MarkItDown(enable_plugins=enable_plugins, **kwargs)
    result = converter.convert(str(pdf_path))
    text = getattr(result, "text_content", None)
    if not text:
        raise OcrProviderError("MarkItDown returned empty markdown")
    text_dir = out_dir / "markitdown_markdown"
    text_dir.mkdir(parents=True, exist_ok=True)
    text_path = text_dir / f"{pdf_path.stem}.md"
    text_path.write_text(str(text), encoding="utf-8")
    return OcrResult(pdf_path, "markitdown", credential.env_name, text_path=text_path)


def ocr_with_rotation(
    pdf_path: Path,
    out_dir: Path,
    providers: Iterable[str],
    language: str = "english",
) -> OcrResult:
    errors: list[str] = []
    credentials = discover_credentials(providers)
    if not credentials:
        raise OcrProviderError("No OCR credentials found in .env for the selected providers.")

    # Gemini: pass all keys at once so they rotate per page
    gemini_creds = [c for c in credentials if c.provider == "gemini_ocr"]
    if gemini_creds:
        try:
            return run_gemini_ocr(pdf_path, out_dir, gemini_creds)
        except Exception as exc:
            errors.append(f"gemini_ocr: {exc}")

    for credential in credentials:
        if credential.provider == "gemini_ocr":
            continue  # already attempted above
        try:
            if credential.provider == "llamacloud":
                return run_llamacloud(pdf_path, out_dir, credential)
            if credential.provider == "nutrient":
                return run_nutrient(pdf_path, out_dir, credential, language=language)
            if credential.provider == "glm_ocr":
                return run_glm_ocr(pdf_path, out_dir, credential)
            if credential.provider == "markitdown":
                return run_markitdown(pdf_path, out_dir, credential)
        except Exception as exc:
            errors.append(f"{credential.provider}:{credential.env_name}: {exc}")
            continue

    raise OcrProviderError("All OCR credentials/providers failed: " + " | ".join(errors))


def _pdf_ac_no(path: Path) -> int | None:
    match = re.search(r"AC0*([0-9]+)PART", path.name, re.I)
    if match:
        return int(match.group(1))
    if path.name[:1].isdigit():
        return int(path.name.split("_", 1)[0])
    return None


def ocr_pdf_dir(
    pdf_dir: Path,
    out_dir: Path,
    providers: Iterable[str],
    language: str = "english",
    overwrite: bool = False,
    acs: Iterable[int] | None = None,
    limit: int | None = None,
    recursive: bool = False,
) -> tuple[list[OcrResult], list[dict[str, str]]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[OcrResult] = []
    failures: list[dict[str, str]] = []
    ac_set = set(acs) if acs else None
    pdf_iter = pdf_dir.rglob("*.pdf") if recursive else pdf_dir.glob("*.pdf")
    pdf_paths = sorted(pdf_iter, key=lambda path: (_pdf_ac_no(path) or 9999, str(path)))
    if ac_set is not None:
        pdf_paths = [path for path in pdf_paths if _pdf_ac_no(path) in ac_set]
    processed_count = 0
    for pdf_path in pdf_paths:
        if limit is not None and processed_count >= limit:
            break
        marker = out_dir / ".done" / f"{pdf_path.stem}.json"
        if marker.exists() and not overwrite:
            continue
        try:
            result = ocr_with_rotation(pdf_path, out_dir, providers, language=language)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                json.dumps(
                    {
                        "source_pdf": str(pdf_path),
                        "provider": result.provider,
                        "credential_name": result.credential_name,
                        "text_path": str(result.text_path) if result.text_path else None,
                        "searchable_pdf_path": str(result.searchable_pdf_path)
                        if result.searchable_pdf_path
                        else None,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            results.append(result)
            processed_count += 1
        except Exception as exc:
            failures.append({"source_pdf": pdf_path.name, "error": str(exc)})
            processed_count += 1
    return results, failures
