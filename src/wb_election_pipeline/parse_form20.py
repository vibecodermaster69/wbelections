from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pdfplumber


TOTAL_MARKERS = {
    "TOTAL OF VALID VOTES",
    "TOTAL NO. OF VALID VOTES",
    "TOTAL NO OF VALID VOTES",
    "TOTAL VALID VOTES",
    "TOTAL NO. OF VOTES",
    "NO. OF TOTAL VALID VOTES",
    "NO OF TOTAL VALID VOTES",
    "NO. OF VALID VOTES CAST IN FAVOUR",
    "NO OF VALID VOTES CAST IN FAVOUR",
    "NO OF REJECTED VOTES",
    "NO. OF REJECTED VOTES",
    "NO. OF TENDERED VOTES",
    "NOTA",
    "TOTAL",
    "TOTAL OF TENDERED VOTES",
    "TOTAL OF TENDERED VOTES",
}


@dataclass(frozen=True)
class Form20Meta:
    ac_no: int | None
    ac_name: str | None
    total_electors: int | None


OUTPUT_COLUMNS = [
    "ac_no",
    "ac_name",
    "total_electors",
    "polling_station",
    "candidate",
    "votes",
    "total_valid_votes",
    "rejected_votes",
    "nota_votes",
    "total_votes_cast",
    "source_pdf",
]


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\n", " ").split())


def parse_metadata(text: str, fallback_ac_no: int | None = None) -> Form20Meta:
    total_electors = None
    electors_match = re.search(r"Total\s+no\.?\s+of\s+electors.*?:\s*([0-9,]+)", text, re.I)
    if electors_match:
        total_electors = int(electors_match.group(1).replace(",", ""))

    ac_no = fallback_ac_no
    ac_name = None
    ac_match = re.search(
        r"Assembly\s+Constituency\s*:?\s*([0-9]{1,3})\s*[- ]\s*([^\n\r]+)",
        text,
        re.I,
    )
    if not ac_match:
        ac_match = re.search(
            r"from\s+the\s+([0-9]{1,3})\s*[- ]\s*([^\n\r]+?)\s+Assembly\s+Constituency",
            text,
            re.I,
        )
    if ac_match:
        ac_no = int(ac_match.group(1))
        ac_name = clean_cell(ac_match.group(2))
    return Form20Meta(ac_no=ac_no, ac_name=ac_name, total_electors=total_electors)


def _is_int(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9]+", value.replace(",", "")))


def _to_int(value: str) -> int | None:
    value = value.replace(",", "")
    return int(value) if _is_int(value) else None


def _find_polling_col(rows: list[list[str]]) -> int:
    for row in rows[:8]:
        for idx, cell in enumerate(row):
            upper = cell.upper()
            if "POLLING" in upper and "STATION" in upper:
                return idx
    return 1


def _candidate_columns(rows: list[list[str]], polling_col: int) -> list[tuple[int, str]]:
    header_blob_by_col: dict[int, str] = {}
    for row in rows[:8]:
        for idx, cell in enumerate(row):
            if idx <= polling_col:
                continue
            if cell:
                header_blob_by_col[idx] = (header_blob_by_col.get(idx, "") + " " + cell).strip()

    candidates: list[tuple[int, str]] = []
    for idx in sorted(header_blob_by_col):
        name = header_blob_by_col[idx]
        upper = name.upper()
        if any(marker in upper for marker in TOTAL_MARKERS):
            break
        if "VALID VOTES CAST IN FAVOUR" in upper:
            continue
        if name and not _is_int(name):
            candidates.append((idx, name))
    return candidates


def _data_rows(rows: list[list[str]], polling_col: int, candidate_cols: list[tuple[int, str]]) -> list[dict[str, object]]:
    parsed: list[dict[str, object]] = []
    if not candidate_cols:
        return parsed

    for row in rows:
        if len(row) <= polling_col:
            continue
        polling_station = clean_cell(row[polling_col])
        if not polling_station or "POLLING" in polling_station.upper():
            continue
        first_vote_idx = candidate_cols[0][0]
        if len(row) <= first_vote_idx or _to_int(clean_cell(row[first_vote_idx])) is None:
            continue
        for idx, candidate in candidate_cols:
            if idx >= len(row):
                continue
            votes = _to_int(clean_cell(row[idx]))
            if votes is None:
                continue
            parsed.append(
                {
                    "polling_station": polling_station,
                    "candidate": candidate,
                    "votes": votes,
                    "total_valid_votes": None,
                    "rejected_votes": None,
                    "nota_votes": None,
                    "total_votes_cast": None,
                }
            )
    return parsed


def parse_form20_pdf(path: Path) -> pd.DataFrame:
    fallback_ac_no = int(path.name.split("_", 1)[0]) if path.name[:1].isdigit() else None
    all_records: list[dict[str, object]] = []
    metadata = Form20Meta(fallback_ac_no, None, None)

    saw_extractable_content = False
    with pdfplumber.open(path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages[:2])
        saw_extractable_content = bool(full_text.strip())
        metadata = parse_metadata(full_text, fallback_ac_no)
        for page in pdf.pages:
            tables = page.extract_tables(
                {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 3,
                    "join_tolerance": 3,
                    "intersection_tolerance": 5,
                }
            )
            if not tables:
                tables = page.extract_tables()
            if tables:
                saw_extractable_content = True
            for table in tables:
                rows = [[clean_cell(cell) for cell in row] for row in table if row]
                if len(rows) < 3:
                    continue
                polling_col = _find_polling_col(rows)
                candidate_cols = _candidate_columns(rows, polling_col)
                all_records.extend(_data_rows(rows, polling_col, candidate_cols))

    df = pd.DataFrame(all_records)
    if df.empty and not saw_extractable_content:
        raise ValueError(
            f"{path.name} appears to be scanned/image-only. Run OCR first or use a manual "
            "candidate-column extraction workflow for this PDF."
        )
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    df.insert(0, "total_electors", metadata.total_electors)
    df.insert(0, "ac_name", metadata.ac_name)
    df.insert(0, "ac_no", metadata.ac_no)
    df["source_pdf"] = path.name
    for column in OUTPUT_COLUMNS:
        if column not in df.columns:
            df[column] = None
    df = df[OUTPUT_COLUMNS]
    return df


def parse_pdf_dir(pdf_dir: Path, out_csv: Path) -> pd.DataFrame:
    frames = []
    failures: list[dict[str, str]] = []
    for pdf in sorted(pdf_dir.glob("*_Form20.pdf"), key=lambda p: int(p.name.split("_", 1)[0])):
        try:
            parsed = parse_form20_pdf(pdf)
        except Exception as exc:
            failures.append({"source_pdf": pdf.name, "error": str(exc)})
            continue
        if not parsed.empty:
            frames.append(parsed)
    if frames:
        combined = pd.concat(frames, ignore_index=True)
    else:
        combined = pd.DataFrame(columns=OUTPUT_COLUMNS)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_csv, index=False)
    if failures:
        pd.DataFrame(failures).to_csv(out_csv.with_suffix(".failures.csv"), index=False)
    elif out_csv.with_suffix(".failures.csv").exists():
        out_csv.with_suffix(".failures.csv").unlink()
    return combined


def _split_markdown_row(line: str) -> list[str]:
    return [clean_cell(cell) for cell in line.strip().strip("|").split("|")]


def _is_markdown_separator(row: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in row if cell)


def _markdown_tables(text: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in text.splitlines():
        if line.strip().startswith("|") and line.strip().endswith("|"):
            current.append(_split_markdown_row(line))
        elif current:
            if len(current) >= 3:
                tables.append(current)
            current = []
    if len(current) >= 3:
        tables.append(current)
    return tables


def _find_markdown_polling_col(header: list[str]) -> int | None:
    for idx, cell in enumerate(header):
        upper = cell.upper()
        if "POLLING" in upper and "STATION" in upper:
            return idx
        compact = upper.replace(".", "").replace(" ", "")
        if compact in {"PSNO", "PSNUMBER", "POLLINGSTATIONNO", "POLLINGSTATIONNUMBER"}:
            return idx
    return None


def _find_markdown_total_col(header: list[str]) -> int | None:
    for idx, cell in enumerate(header):
        upper = cell.upper()
        if (
            "TOTAL OF VALID" in upper
            or "TOTAL NO. OF VALID" in upper
            or "TOTAL NO OF VALID" in upper
            or "TOTAL VALID VOTES" in upper
            or "TOTAL NO. OF VOTES" in upper
            or "TOTAL NO OF VOTES" in upper
            or "NO. OF TOTAL VALID" in upper
            or "NO OF TOTAL VALID" in upper
        ):
            return idx
    return None


def _looks_like_polling_station(value: str) -> bool:
    text = clean_cell(value).upper()
    return bool(re.fullmatch(r"[0-9]{1,4}\s*(?:\(?[A-Z]\)?)?", text))


def _fallback_polling_col(header: list[str], rows: list[list[str]]) -> int | None:
    if not header or "SERIAL" not in header[0].upper():
        return None
    candidates = [1, 2]
    best_col = None
    best_hits = 0
    for col in candidates:
        hits = 0
        for row in rows[:50]:
            if len(row) > col and _looks_like_polling_station(row[col]):
                hits += 1
        if hits > best_hits:
            best_col = col
            best_hits = hits
    return best_col if best_hits >= 3 else None


def _numeric_indices(row: list[str]) -> list[int]:
    return [
        idx
        for idx, cell in enumerate(row)
        if _to_int(cell.replace("O", "0").replace("o", "0")) is not None
    ]


def _infer_total_valid_col(rows: list[list[str]], polling_col: int, header_total_col: int | None) -> int | None:
    usable_last_indices: list[int] = []
    for row in rows:
        if len(row) <= polling_col or not row[polling_col]:
            continue
        numeric = _numeric_indices(row)
        numeric_after_polling = [idx for idx in numeric if idx > polling_col]
        if len(numeric_after_polling) >= 5:
            usable_last_indices.append(max(numeric_after_polling))
    if not usable_last_indices:
        return header_total_col
    usable_last_indices.sort()
    median_last = usable_last_indices[len(usable_last_indices) // 2]
    inferred = median_last - 4
    if header_total_col is None:
        return inferred if inferred > polling_col else None
    if header_total_col > median_last or header_total_col <= polling_col:
        return inferred if inferred > polling_col else None
    return header_total_col


def _find_header_col(header: list[str], patterns: tuple[str, ...], start: int = 0) -> int | None:
    for idx, cell in enumerate(header[start:], start=start):
        upper = cell.upper()
        if any(pattern in upper for pattern in patterns):
            return idx
    return None


def _cell_int(row: list[str], idx: int | None) -> int | None:
    if idx is None or idx >= len(row):
        return None
    return _to_int(row[idx].replace("O", "0").replace("o", "0").replace(".", ""))


def parse_llamacloud_markdown(path: Path) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8")
    filename_ac_no = int(path.name.split("_", 1)[0]) if path.name[:1].isdigit() else None
    metadata = parse_metadata(text, filename_ac_no)
    metadata = Form20Meta(
        ac_no=filename_ac_no or metadata.ac_no,
        ac_name=metadata.ac_name,
        total_electors=metadata.total_electors,
    )
    records: list[dict[str, object]] = []

    for table in _markdown_tables(text):
        header = table[0]
        if len(table) > 1 and _is_markdown_separator(table[1]):
            rows = table[2:]
        else:
            rows = table[1:]
        polling_col = _find_markdown_polling_col(header)
        if polling_col is None:
            polling_col = _fallback_polling_col(header, rows)
        total_col = _infer_total_valid_col(rows, polling_col, _find_markdown_total_col(header)) if polling_col is not None else None
        if polling_col is None or total_col is None or total_col <= polling_col + 1:
            continue
        rejected_col = _find_header_col(header, ("REJECTED",), start=total_col + 1)
        nota_col = _find_header_col(header, ("NOTA",), start=total_col + 1)
        total_votes_cast_col = _find_header_col(
            header,
            ("TOTAL VOTES", "TOTAL VOTE", "TOTAL TENDERED", "TOTAL TENDER"),
            start=total_col + 1,
        )

        candidate_headers = []
        for idx in range(polling_col + 1, total_col):
            name = header[idx] if idx < len(header) else ""
            if any(marker in name.upper() for marker in TOTAL_MARKERS):
                continue
            if not name:
                name = f"candidate_col_{idx - polling_col}"
            candidate_headers.append((idx, name))

        for row in rows:
            if len(row) <= total_col:
                continue
            polling_station = row[polling_col]
            if not polling_station or not _looks_like_polling_station(polling_station):
                continue
            total_valid = _to_int(row[total_col].replace("O", "0").replace("o", "0"))
            if total_valid is None:
                continue
            rejected_votes = _cell_int(row, rejected_col)
            nota_votes = _cell_int(row, nota_col)
            total_votes_cast = _cell_int(row, total_votes_cast_col)
            if total_votes_cast is None and nota_votes is not None:
                total_votes_cast = total_valid + nota_votes + (rejected_votes or 0)
            row_candidate_values: list[tuple[int, str, int]] = []
            for idx, candidate in candidate_headers:
                if idx >= len(row):
                    continue
                votes = _to_int(row[idx].replace("O", "0").replace("o", "0"))
                if votes is None:
                    continue
                row_candidate_values.append((idx, candidate, votes))
            if not row_candidate_values:
                continue
            max_candidate_votes = max(votes for _, _, votes in row_candidate_values)
            plausible_totals = total_valid >= max_candidate_votes and (
                total_votes_cast is None or total_votes_cast >= total_valid
            )
            if not plausible_totals:
                total_valid_out = None
                rejected_votes_out = None
                nota_votes_out = None
                total_votes_cast_out = None
            else:
                total_valid_out = total_valid
                rejected_votes_out = rejected_votes
                nota_votes_out = nota_votes
                total_votes_cast_out = total_votes_cast
            for _, candidate, votes in row_candidate_values:
                records.append(
                    {
                        "ac_no": metadata.ac_no,
                        "ac_name": metadata.ac_name,
                        "total_electors": metadata.total_electors,
                        "polling_station": polling_station,
                        "candidate": candidate,
                        "votes": votes,
                        "total_valid_votes": total_valid_out,
                        "rejected_votes": rejected_votes_out,
                        "nota_votes": nota_votes_out,
                        "total_votes_cast": total_votes_cast_out,
                        "source_pdf": path.with_suffix(".pdf").name,
                    }
                )

    return pd.DataFrame(records, columns=OUTPUT_COLUMNS)


def parse_llamacloud_markdown_dir(markdown_dir: Path, out_csv: Path) -> pd.DataFrame:
    frames = []
    failures: list[dict[str, str]] = []
    for markdown in sorted(markdown_dir.glob("*.md")):
        try:
            parsed = parse_llamacloud_markdown(markdown)
        except Exception as exc:
            failures.append({"source_pdf": markdown.with_suffix(".pdf").name, "error": str(exc)})
            continue
        if not parsed.empty:
            frames.append(parsed)
        else:
            failures.append({"source_pdf": markdown.with_suffix(".pdf").name, "error": "No Form 20 markdown tables parsed"})
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_csv, index=False)
    if failures:
        pd.DataFrame(failures).to_csv(out_csv.with_suffix(".failures.csv"), index=False)
    elif out_csv.with_suffix(".failures.csv").exists():
        out_csv.with_suffix(".failures.csv").unlink()
    return combined


def parse_gemini_markdown(path: Path) -> pd.DataFrame:
    """Parse Gemini OCR markdown for Form 20.

    Like parse_llamacloud_markdown but normalises candidate names across pages
    by position — Gemini OCR often produces slightly different spellings for the
    same candidate on different pages.  The most-common non-placeholder spelling
    per column position is used as the canonical name.
    """
    from collections import Counter

    text = path.read_text(encoding="utf-8")
    filename_ac_no = int(path.name.split("_", 1)[0]) if path.name[:1].isdigit() else None
    metadata = Form20Meta(ac_no=filename_ac_no, ac_name=None, total_electors=None)

    # --- First pass: extract per-page table info ---
    page_data: list[dict] = []
    for table in _markdown_tables(text):
        header = table[0]
        rows = table[2:] if len(table) > 1 and _is_markdown_separator(table[1]) else table[1:]
        polling_col = _find_markdown_polling_col(header)
        if polling_col is None:
            polling_col = _fallback_polling_col(header, rows)
        total_col = (
            _infer_total_valid_col(rows, polling_col, _find_markdown_total_col(header))
            if polling_col is not None
            else None
        )
        if polling_col is None or total_col is None or total_col <= polling_col + 1:
            continue
        rejected_col = _find_header_col(header, ("REJECTED",), start=total_col + 1)
        nota_col = _find_header_col(header, ("NOTA",), start=total_col + 1)
        total_votes_cast_col = _find_header_col(
            header,
            ("TOTAL VOTES", "TOTAL VOTE", "TOTAL TENDERED", "TOTAL TENDER"),
            start=total_col + 1,
        )
        candidate_headers: list[tuple[int, str]] = []
        for idx in range(polling_col + 1, total_col):
            name = header[idx] if idx < len(header) else ""
            if any(marker in name.upper() for marker in TOTAL_MARKERS):
                continue
            if not name:
                name = f"candidate_col_{idx - polling_col}"
            candidate_headers.append((idx, name))
        page_data.append(
            dict(
                rows=rows,
                polling_col=polling_col,
                total_col=total_col,
                rejected_col=rejected_col,
                nota_col=nota_col,
                total_votes_cast_col=total_votes_cast_col,
                candidate_headers=candidate_headers,
            )
        )

    if not page_data:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # --- Build canonical candidate names by column position ---
    n_candidates = max(len(p["candidate_headers"]) for p in page_data)
    pos_counters: dict[int, Counter] = {i: Counter() for i in range(n_candidates)}
    for p in page_data:
        for pos, (_, name) in enumerate(p["candidate_headers"]):
            if not name.startswith("candidate_col_"):
                pos_counters[pos][name] += 1
    canonical_names: dict[int, str] = {
        pos: (ctr.most_common(1)[0][0] if ctr else f"candidate_col_{pos + 1}")
        for pos, ctr in pos_counters.items()
    }

    # --- Second pass: emit records with canonical names ---
    records: list[dict] = []
    for p in page_data:
        polling_col = p["polling_col"]
        total_col = p["total_col"]
        canonical_candidate_headers = [
            (idx, canonical_names.get(pos, f"candidate_col_{pos + 1}"))
            for pos, (idx, _) in enumerate(p["candidate_headers"])
        ]
        for row in p["rows"]:
            if len(row) <= total_col:
                continue
            polling_station = row[polling_col]
            if not polling_station or not _looks_like_polling_station(polling_station):
                continue
            total_valid = _to_int(row[total_col].replace("O", "0").replace("o", "0"))
            if total_valid is None:
                continue
            rejected_votes = _cell_int(row, p["rejected_col"])
            nota_votes = _cell_int(row, p["nota_col"])
            total_votes_cast = _cell_int(row, p["total_votes_cast_col"])
            if total_votes_cast is None and nota_votes is not None:
                total_votes_cast = total_valid + nota_votes + (rejected_votes or 0)
            row_candidate_values: list[tuple[int, str, int]] = []
            for idx, candidate in canonical_candidate_headers:
                if idx >= len(row):
                    continue
                votes = _to_int(row[idx].replace("O", "0").replace("o", "0"))
                if votes is None:
                    continue
                row_candidate_values.append((idx, candidate, votes))
            if not row_candidate_values:
                continue
            max_candidate_votes = max(v for _, _, v in row_candidate_values)
            plausible = total_valid >= max_candidate_votes and (
                total_votes_cast is None or total_votes_cast >= total_valid
            )
            tv = total_valid if plausible else None
            rv = rejected_votes if plausible else None
            nv = nota_votes if plausible else None
            tvc = total_votes_cast if plausible else None
            for _, candidate, votes in row_candidate_values:
                records.append(
                    {
                        "ac_no": metadata.ac_no,
                        "ac_name": metadata.ac_name,
                        "total_electors": metadata.total_electors,
                        "polling_station": polling_station,
                        "candidate": candidate,
                        "votes": votes,
                        "total_valid_votes": tv,
                        "rejected_votes": rv,
                        "nota_votes": nv,
                        "total_votes_cast": tvc,
                        "source_pdf": path.with_suffix(".pdf").name,
                    }
                )

    return pd.DataFrame(records, columns=OUTPUT_COLUMNS)


def parse_gemini_markdown_dir(markdown_dir: Path, out_csv: Path) -> pd.DataFrame:
    frames = []
    failures: list[dict[str, str]] = []
    for markdown in sorted(markdown_dir.glob("*.md")):
        try:
            parsed = parse_gemini_markdown(markdown)
        except Exception as exc:
            failures.append({"source_pdf": markdown.with_suffix(".pdf").name, "error": str(exc)})
            continue
        if not parsed.empty:
            frames.append(parsed)
        else:
            failures.append(
                {"source_pdf": markdown.with_suffix(".pdf").name, "error": "No Form 20 tables parsed"}
            )
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_csv, index=False)
    if failures:
        pd.DataFrame(failures).to_csv(out_csv.with_suffix(".failures.csv"), index=False)
    elif out_csv.with_suffix(".failures.csv").exists():
        out_csv.with_suffix(".failures.csv").unlink()
    return combined
