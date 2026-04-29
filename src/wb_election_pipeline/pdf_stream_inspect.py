from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any


ASCII_SERIAL_RE = re.compile(rb"(?<![0-9])(?:[1-9][0-9]{0,3})(?![0-9])")
PDF_TEXT_OPERATOR_RE = re.compile(rb"\b(?:BT|ET|TJ|Tj|Tm|Td|TD)\b")
HEX_STRING_RE = re.compile(rb"<[0-9A-Fa-f\s]{4,}>")
LITERAL_STRING_RE = re.compile(rb"\((?:\\.|[^\\)]){0,500}\)")


def _sample_matches(data: bytes, pattern: re.Pattern[bytes], limit: int = 12, context: int = 24) -> list[str]:
    samples: list[str] = []
    for match in pattern.finditer(data):
        start = max(0, match.start() - context)
        end = min(len(data), match.end() + context)
        snippet = data[start:end]
        samples.append(snippet.decode("latin-1", errors="replace").replace("\r", "\\r").replace("\n", "\\n"))
        if len(samples) >= limit:
            break
    return samples


def _stream_stats(data: bytes) -> dict[str, Any]:
    ascii_serials = ASCII_SERIAL_RE.findall(data)
    unique_serials = sorted({int(value) for value in ascii_serials if value.isdigit()})
    return {
        "bytes": len(data),
        "ascii_serial_token_count": len(ascii_serials),
        "ascii_serial_unique_count": len(unique_serials),
        "ascii_serial_min": unique_serials[0] if unique_serials else None,
        "ascii_serial_max": unique_serials[-1] if unique_serials else None,
        "pdf_text_operator_count": len(PDF_TEXT_OPERATOR_RE.findall(data)),
        "hex_string_count": len(HEX_STRING_RE.findall(data)),
        "ascii_serial_samples": _sample_matches(data, ASCII_SERIAL_RE),
    }


def _text_operand_bytes(data: bytes) -> bytes:
    chunks: list[bytes] = []
    for match in LITERAL_STRING_RE.finditer(data):
        chunks.append(match.group(0))
    return b"\n".join(chunks)


def inspect_pdf_streams(pdf_path: Path, out_json: Path | None = None, stream_sample_limit: int = 20) -> dict[str, Any]:
    import fitz

    doc = fitz.open(str(pdf_path))
    stream_summaries: list[dict[str, Any]] = []
    total_raw_bytes = 0
    total_decoded_bytes = 0
    all_raw = bytearray()
    all_decoded = bytearray()
    all_text_operands = bytearray()
    stream_count = 0

    for xref in range(1, doc.xref_length()):
        try:
            raw = doc.xref_stream_raw(xref)
        except Exception:
            raw = None
        try:
            decoded = doc.xref_stream(xref)
        except Exception:
            decoded = None
        if raw is None and decoded is None:
            continue

        stream_count += 1
        raw = raw or b""
        decoded = decoded or b""
        total_raw_bytes += len(raw)
        total_decoded_bytes += len(decoded)
        all_raw.extend(raw[:250000])
        all_decoded.extend(decoded[:250000])
        all_text_operands.extend(_text_operand_bytes(decoded)[:250000])

        if len(stream_summaries) < stream_sample_limit:
            text_operands = _text_operand_bytes(decoded)
            stream_summaries.append(
                {
                    "xref": xref,
                    "raw": _stream_stats(raw),
                    "decoded": _stream_stats(decoded),
                    "text_operands": _stream_stats(text_operands),
                }
            )

    trailer = doc.pdf_trailer()
    raw_pdf = pdf_path.read_bytes()
    summary: dict[str, Any] = {
        "pdf": str(pdf_path),
        "pages": doc.page_count,
        "xref_length": doc.xref_length(),
        "stream_count": stream_count,
        "total_raw_stream_bytes": total_raw_bytes,
        "total_decoded_stream_bytes": total_decoded_bytes,
        "document_markers": {
            "has_cidfont": b"CIDFont" in raw_pdf,
            "has_tounicode": b"ToUnicode" in raw_pdf,
            "has_identity_h": b"Identity-H" in raw_pdf,
            "has_bengali_utf8_bytes": bool(re.search(b"[\xe0-\xe0][\xa6-\xa7]", raw_pdf)),
        },
        "aggregate_raw": _stream_stats(bytes(all_raw)),
        "aggregate_decoded": _stream_stats(bytes(all_decoded)),
        "aggregate_text_operands": _stream_stats(bytes(all_text_operands)),
        "sample_streams": stream_summaries,
        "trailer_sample": trailer[:1000],
    }
    doc.close()

    if out_json is not None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
