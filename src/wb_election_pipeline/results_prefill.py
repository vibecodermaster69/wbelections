from __future__ import annotations

from difflib import SequenceMatcher
from io import StringIO
from pathlib import Path
import re

import pandas as pd
import requests

from .party import normalize_party

ECI_RESULT_BASE_URL = "https://results.eci.gov.in/Result2021"
ECI_SEARCH_URL = f"{ECI_RESULT_BASE_URL}/search.htm"
ECI_WB_STATE_CODE = "S25"
MODEL_PARTIES = {"TMC", "BJP", "INC", "CPM", "ISF", "OTHER"}
PARTY_TEXT_ALIASES = {
    "AITC": "TMC",
    "TMC": "TMC",
    "BJP": "BJP",
    "INC": "INC",
    "CONGRESS": "INC",
    "CPM": "CPM",
    "CPIM": "CPM",
    "CPI M": "CPM",
    "CPI MARXIST": "CPM",
    "ISF": "ISF",
    "IND": "OTHER",
    "INDEPENDENT": "OTHER",
    "NOTA": "OTHER",
    "BSP": "OTHER",
    "RSP": "OTHER",
    "AIFB": "OTHER",
    "SUCI": "OTHER",
    "SUCIC": "OTHER",
    "CPI": "OTHER",
    "KPPU": "OTHER",
    "PPUTD": "OTHER",
    "K PPUTD": "OTHER",
    "GJM": "OTHER",
}


def normalize_model_party(value: object) -> str:
    text = " ".join(str(value or "").upper().replace(".", " ").split())
    party = normalize_party(value)
    if text in {"INDIAN NATIONAL CONGRESS", "INC"}:
        return "INC"
    if text in {"COMMUNIST PARTY OF INDIA (MARXIST)", "COMMUNIST PARTY OF INDIA MARXIST"}:
        return "CPM"
    if text in {"INDIAN SECULAR FRONT", "ISF"}:
        return "ISF"
    if party in {"CPI(M)", "CPIM", "CPI M"}:
        return "CPM"
    if party in {"AITC", "TMC"}:
        return "TMC"
    if party in {"BJP", "INC", "CPM", "ISF"}:
        return party
    return "OTHER"


def normalize_name(value: object) -> str:
    text = " ".join(str(value or "").upper().replace(".", " ").split())
    return "".join(ch for ch in text if ch.isalnum() or ch.isspace()).strip()


def clean_eci_candidate_name(value: object) -> str:
    text = " ".join(str(value or "").split())
    return re.sub(r"^\d+\s+", "", text).strip()


def _meaningful_tokens(value: object) -> list[str]:
    return [token for token in normalize_name(value).split() if len(token) >= 3 and not token.isdigit()]


def _flat_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            "_".join(str(part) for part in col if str(part) != "nan").strip("_")
            for col in df.columns
        ]
    return df


def _column_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _read_tabular_candidate_results(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        preview = pd.read_excel(path, sheet_name=0, header=None, nrows=25)
        header_row = None
        for idx, row in preview.iterrows():
            keys = {_column_key(value) for value in row.tolist()}
            if {"ac_no", "candidate_name", "party"}.issubset(keys) or {"ac_no", "candidate", "party"}.issubset(keys):
                header_row = idx
                break
        if header_row is None:
            raise ValueError(f"Could not locate ECI detailed-results header row in {path}")
        return pd.read_excel(path, sheet_name=0, header=header_row)
    return pd.read_csv(path)


def _request_eci(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=45,
    )
    if response.status_code in {401, 403}:
        raise RuntimeError(f"ECI blocked direct download for {url}: HTTP {response.status_code}")
    response.raise_for_status()
    text = response.text
    if "Access Denied" in text[:1000]:
        raise RuntimeError(f"ECI blocked direct download for {url}")
    return text


def _load_scope(scope_csv: Path | None) -> pd.DataFrame | None:
    if scope_csv is None:
        return None
    scope = pd.read_csv(scope_csv)
    scope["ac_no"] = pd.to_numeric(scope["ac_no"], errors="coerce").astype("Int64")
    if "ac_name" in scope.columns:
        scope["ac_name_key"] = scope["ac_name"].map(normalize_name)
    return scope


def _standardize_candidate_results(results: pd.DataFrame, scope_csv: Path | None = None) -> pd.DataFrame:
    candidates = results.copy()
    candidates.columns = [_column_key(col) for col in candidates.columns]
    rename = {
        "assembly_constituency": "ac_name",
        "constituency": "ac_name",
        "candidate_name": "candidate",
        "party_name": "party",
        "ac": "ac_no",
        "const_no": "ac_no",
        "total_votes_polled": "total_votes",
        "total_votes": "total_votes",
        "total": "total_votes",
        "total_vote": "total_votes",
    }
    candidates = candidates.rename(columns={key: value for key, value in rename.items() if key in candidates.columns})
    required = {"candidate", "party"}
    missing = required - set(candidates.columns)
    if missing:
        raise ValueError(f"ECI candidate results missing columns: {sorted(missing)}")

    if "ac_no" not in candidates.columns:
        if "ac_name" not in candidates.columns:
            raise ValueError("ECI candidate results need either ac_no or ac_name")
        scope = _load_scope(scope_csv)
        if scope is None:
            raise ValueError("scope_csv is required when ECI candidate results do not include ac_no")
        if "ac_name_key" not in scope.columns:
            raise ValueError("ECI candidate results without ac_no require a scope CSV with ac_name")
        candidates["ac_name_key"] = candidates["ac_name"].map(normalize_name)
        candidates = candidates.merge(scope[["ac_no", "ac_name_key"]], on="ac_name_key", how="inner")

    candidates["ac_no"] = pd.to_numeric(candidates["ac_no"], errors="coerce").astype("Int64")
    if "ac_name" not in candidates.columns:
        scope = _load_scope(scope_csv)
        if scope is not None and "ac_name" in scope.columns:
            candidates = candidates.merge(scope[["ac_no", "ac_name"]], on="ac_no", how="left")
        else:
            candidates["ac_name"] = ""
    if "total_votes" not in candidates.columns:
        candidates["total_votes"] = pd.NA
    if "source" not in candidates.columns:
        candidates["source"] = "ECI"
    candidates["party"] = candidates["party"].map(normalize_model_party)
    candidates["candidate"] = candidates["candidate"].map(clean_eci_candidate_name)
    candidates = candidates.dropna(subset=["ac_no", "candidate"])
    candidates = candidates[candidates["candidate"].astype(str).str.upper().str.strip() != "TOTAL"]
    scope = _load_scope(scope_csv)
    if scope is not None:
        candidates = candidates[candidates["ac_no"].isin(scope["ac_no"])]
    return candidates[["ac_no", "ac_name", "candidate", "party", "total_votes", "source"]].drop_duplicates()


def _candidate_rows_from_constituency_page(ac_no: int, ac_name: str | None = None) -> list[dict[str, object]]:
    url = f"{ECI_RESULT_BASE_URL}/Constituencywise{ECI_WB_STATE_CODE}{ac_no}.htm?ac={ac_no}"
    html = _request_eci(url)
    tables = pd.read_html(StringIO(html))
    rows: list[dict[str, object]] = []
    for table in tables:
        table = _flat_columns(table)
        columns = {str(col).strip().lower().replace(" ", "_"): col for col in table.columns}
        if not {"candidate", "party"}.issubset(columns):
            continue
        candidate_col = columns["candidate"]
        party_col = columns["party"]
        votes_col = columns.get("total_votes") or columns.get("total")
        for _, record in table.iterrows():
            candidate = record.get(candidate_col)
            if not isinstance(candidate, str) or candidate.strip().upper() == "TOTAL":
                continue
            rows.append(
                {
                    "ac_no": ac_no,
                    "ac_name": ac_name or "",
                    "candidate": candidate,
                    "party": record.get(party_col),
                    "total_votes": record.get(votes_col) if votes_col else pd.NA,
                    "source": url,
                }
            )
        if rows:
            break
    return rows


def _candidate_rows_from_search_page(scope_csv: Path | None = None) -> pd.DataFrame:
    html = _request_eci(ECI_SEARCH_URL)
    tables = pd.read_html(StringIO(html))
    rows: list[pd.DataFrame] = []
    for table in tables:
        table = _flat_columns(table)
        normalized = {str(col).strip().lower().replace(" ", "_"): col for col in table.columns}
        if {"candidate", "constituency", "party", "state"}.issubset(normalized):
            table = table.rename(
                columns={
                    normalized["candidate"]: "candidate",
                    normalized["constituency"]: "ac_name",
                    normalized["party"]: "party",
                    normalized["state"]: "state",
                }
            )
            rows.append(table[table["state"].astype(str).str.casefold() == "west bengal"])
    if not rows:
        raise ValueError("Could not find the ECI candidate search table")
    results = pd.concat(rows, ignore_index=True)
    results["source"] = ECI_SEARCH_URL
    return _standardize_candidate_results(results, scope_csv=scope_csv)


def fetch_eci_candidate_results(
    out_csv: Path,
    scope_csv: Path | None = None,
    input_csv: Path | None = None,
) -> pd.DataFrame:
    """Fetch or import official ECI candidate-party results for 2021 West Bengal.

    Direct ECI pages are preferred. If ECI blocks automated requests, pass an
    official ECI CSV/XLSX exported from the results/statistical-report pages via
    ``input_csv`` and this function will normalize it to the pipeline schema.
    """
    if input_csv is not None:
        results = _standardize_candidate_results(_read_tabular_candidate_results(input_csv), scope_csv=scope_csv)
    else:
        scope = _load_scope(scope_csv)
        rows: list[dict[str, object]] = []
        blocked_urls: list[str] = []
        if scope is not None:
            for record in scope.itertuples(index=False):
                ac_name = getattr(record, "ac_name", "")
                try:
                    rows.extend(_candidate_rows_from_constituency_page(int(record.ac_no), str(ac_name)))
                except RuntimeError as exc:
                    blocked_urls.append(str(exc))
                    break
        if rows:
            results = _standardize_candidate_results(pd.DataFrame(rows), scope_csv=scope_csv)
        else:
            try:
                results = _candidate_rows_from_search_page(scope_csv=scope_csv)
            except RuntimeError as exc:
                detail = "; ".join(blocked_urls + [str(exc)])
                raise RuntimeError(
                    "ECI blocked direct automated download. Download/export the official ECI candidate "
                    "results as CSV and rerun with --input-csv."
                ) from exc

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_csv, index=False)
    return results


def fetch_winner_runner_results(out_csv: Path, scope_csv: Path | None = None) -> pd.DataFrame:
    """Backward-compatible alias for the old CLI/tests.

    The implementation now uses official ECI candidate-level results instead of
    a winner/runner reference table.
    """
    return fetch_eci_candidate_results(out_csv, scope_csv=scope_csv)


def _legacy_winner_runner_lookup(results: pd.DataFrame) -> dict[int, list[tuple[str, str, str]]]:
    rows: list[dict[str, object]] = []
    for row in results.itertuples(index=False):
        if hasattr(row, "winner_candidate") and isinstance(row.winner_candidate, str):
            rows.append(
                {
                    "ac_no": row.ac_no,
                    "candidate": row.winner_candidate,
                    "party": row.winner_party,
                    "source_label": "winner_runner",
                }
            )
        if hasattr(row, "runner_candidate") and isinstance(row.runner_candidate, str):
            rows.append(
                {
                    "ac_no": row.ac_no,
                    "candidate": row.runner_candidate,
                    "party": row.runner_party,
                    "source_label": "winner_runner",
                }
            )
    return _candidate_result_lookup(pd.DataFrame(rows))


def _candidate_result_lookup(results: pd.DataFrame) -> dict[int, list[tuple[str, str, str]]]:
    lookup: dict[int, list[tuple[str, str, str]]] = {}
    if results.empty:
        return lookup
    for row in results.itertuples(index=False):
        candidate = getattr(row, "candidate", None)
        if not isinstance(candidate, str):
            continue
        ac_no = int(row.ac_no)
        party = normalize_model_party(getattr(row, "party", "OTHER"))
        source_label = getattr(row, "source_label", "eci_candidate")
        lookup.setdefault(ac_no, []).append((candidate, party, source_label))
    return lookup


def _reference_candidates_by_ac(results: pd.DataFrame) -> dict[int, list[dict[str, object]]]:
    refs: dict[int, list[dict[str, object]]] = {}
    for row in results.itertuples(index=False):
        candidate = getattr(row, "candidate", None)
        if not isinstance(candidate, str):
            continue
        refs.setdefault(int(row.ac_no), []).append(
            {
                "candidate": candidate,
                "candidate_norm": normalize_name(candidate),
                "tokens": set(_meaningful_tokens(candidate)),
                "party": normalize_model_party(getattr(row, "party", "OTHER")),
            }
        )
    return refs


def _load_overrides(path: Path | None) -> dict[tuple[int, str], tuple[str, str]]:
    if path is None or not path.exists():
        return {}
    overrides = pd.read_csv(path)
    required = {"ac_no", "candidate", "party"}
    missing = required - set(overrides.columns)
    if missing:
        raise ValueError(f"Override file missing columns: {sorted(missing)}")
    loaded: dict[tuple[int, str], tuple[str, str]] = {}
    for row in overrides.itertuples(index=False):
        candidate = getattr(row, "candidate", None)
        if not isinstance(candidate, str):
            continue
        party = normalize_model_party(getattr(row, "party", "OTHER"))
        source = getattr(row, "source", "manual_override")
        loaded[(int(row.ac_no), normalize_name(candidate))] = (party, str(source))
    return loaded


def _party_from_candidate_text(candidate: object) -> tuple[str, str] | None:
    candidate_norm = normalize_name(candidate)
    tokens = candidate_norm.split()
    for width in (2, 1):
        suffix = " ".join(tokens[-width:])
        if suffix in PARTY_TEXT_ALIASES:
            return PARTY_TEXT_ALIASES[suffix], f"candidate_text_party_suffix:{suffix}"
    match = re.search(
        r"\b(AITC|TMC|BJP|INC|CPM|CPI\s*M|ISF|IND|INDEPENDENT|NOTA|BSP|RSP|AIFB|SUCI|SUCIC|CPI|KPPU|PPUTD|GJM)\b",
        candidate_norm,
    )
    if match:
        label = " ".join(match.group(1).split())
        return PARTY_TEXT_ALIASES[label], f"candidate_text_party_token:{label}"
    return None


def _resolve_against_eci(candidate: object, references: list[dict[str, object]]) -> tuple[str, str, float] | None:
    candidate_norm = normalize_name(candidate)
    candidate_tokens = set(_meaningful_tokens(candidate_norm))
    if not candidate_norm or not candidate_tokens:
        return None

    full_matches = [
        ref
        for ref in references
        if candidate_norm == ref["candidate_norm"]
        or (
            len(candidate_tokens) >= 2
            and candidate_tokens.issubset(ref["tokens"])
        )
    ]
    if len(full_matches) == 1:
        ref = full_matches[0]
        return str(ref["party"]), f"eci_unique_token_subset:{ref['candidate']}", 0.94

    if len(candidate_tokens) >= 2:
        overlap_matches = [
            ref
            for ref in references
            if len(candidate_tokens.intersection(ref["tokens"])) >= 2
        ]
        if len(overlap_matches) == 1:
            ref = overlap_matches[0]
            return str(ref["party"]), f"eci_unique_two_token_overlap:{ref['candidate']}", 0.88

    if len(candidate_tokens) == 1:
        token = next(iter(candidate_tokens))
        if len(token) < 4:
            return None
        exact_token_matches = [ref for ref in references if token in ref["tokens"]]
        if len(exact_token_matches) == 1:
            ref = exact_token_matches[0]
            return str(ref["party"]), f"eci_unique_single_token:{ref['candidate']}", 0.91
        fuzzy_token_matches = []
        for ref in references:
            best_token_score = max(
                (SequenceMatcher(None, token, ref_token).ratio() for ref_token in ref["tokens"]),
                default=0.0,
            )
            if best_token_score >= 0.78:
                fuzzy_token_matches.append((best_token_score, ref))
        fuzzy_token_matches.sort(key=lambda item: item[0], reverse=True)
        if fuzzy_token_matches and (
            len(fuzzy_token_matches) == 1
            or fuzzy_token_matches[0][0] - fuzzy_token_matches[1][0] >= 0.12
        ):
            score, ref = fuzzy_token_matches[0]
            return str(ref["party"]), f"eci_unique_single_token_fuzzy:{ref['candidate']}", round(score, 3)

    scored: list[tuple[float, dict[str, object]]] = []
    for ref in references:
        score = _match_score(candidate_norm, str(ref["candidate"]))
        if score >= 0.9:
            scored.append((score, ref))
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08):
        score, ref = scored[0]
        return str(ref["party"]), f"eci_unique_fuzzy:{ref['candidate']}", round(score, 3)
    return None


def _match_score(candidate: str, reference: str) -> float:
    candidate_norm = normalize_name(candidate)
    reference_norm = normalize_name(reference)
    if not candidate_norm or not reference_norm:
        return 0.0
    ratio = SequenceMatcher(None, candidate_norm, reference_norm).ratio()
    candidate_tokens = set(candidate_norm.split())
    reference_tokens = set(reference_norm.split())
    if len(candidate_tokens) >= 2 and candidate_tokens.issubset(reference_tokens):
        ratio = max(ratio, 0.92)
    if len(reference_tokens) >= 2 and reference_tokens.issubset(candidate_tokens):
        ratio = max(ratio, 0.92)
    return ratio


def write_priority_unmapped_party_rows(party_map: pd.DataFrame, out_csv: Path, limit: int = 200) -> pd.DataFrame:
    placeholder = party_map.get("is_placeholder_candidate", False)
    non_candidate = party_map.get("is_non_candidate_header", False)
    if not isinstance(placeholder, pd.Series):
        placeholder = pd.Series(False, index=party_map.index)
    if not isinstance(non_candidate, pd.Series):
        non_candidate = pd.Series(False, index=party_map.index)
    unresolved = party_map[
        party_map["party"].fillna("").eq("")
        & ~placeholder.fillna(False).astype(bool)
        & ~non_candidate.fillna(False).astype(bool)
    ].copy()
    sort_cols = [col for col in ["candidate_votes_total", "booth_count"] if col in unresolved.columns]
    if sort_cols:
        unresolved = unresolved.sort_values(sort_cols, ascending=[False] * len(sort_cols))
    cols = [
        col
        for col in [
            "ac_no",
            "district",
            "ac_name",
            "candidate",
            "candidate_votes_total",
            "booth_count",
            "needs_review",
            "notes",
        ]
        if col in unresolved.columns
    ]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    unresolved[cols].head(limit).to_csv(out_csv, index=False)
    return unresolved


def resolve_candidate_party_map(
    party_map_csv: Path,
    results_csv: Path,
    out_csv: Path,
    unresolved_out_csv: Path | None = None,
    overrides_csv: Path | None = None,
) -> pd.DataFrame:
    party_map = pd.read_csv(party_map_csv)
    results = pd.read_csv(results_csv)
    party_map["ac_no"] = pd.to_numeric(party_map["ac_no"], errors="coerce").astype("Int64")
    results["ac_no"] = pd.to_numeric(results["ac_no"], errors="coerce").astype("Int64")
    references = _reference_candidates_by_ac(results)
    overrides = _load_overrides(overrides_csv)

    resolved = party_map.copy()
    for column, default in [("party", ""), ("prefill_source", ""), ("prefill_score", pd.NA), ("notes", "")]:
        if column not in resolved.columns:
            resolved[column] = default
    resolved["party"] = resolved["party"].fillna("")

    for idx, row in resolved.iterrows():
        if str(row.get("party", "")).strip():
            continue
        if bool(row.get("is_placeholder_candidate", False)) or bool(row.get("is_non_candidate_header", False)):
            continue

        ac_no = int(row["ac_no"])
        override = overrides.get((ac_no, normalize_name(row.get("candidate", ""))))
        if override is not None:
            party, source = override
            resolved.at[idx, "party"] = party
            resolved.at[idx, "prefill_source"] = source
            resolved.at[idx, "prefill_score"] = 1.0
            resolved.at[idx, "needs_review"] = False
            continue

        direct_party = _party_from_candidate_text(row.get("candidate", ""))
        if direct_party is not None:
            party, source = direct_party
            resolved.at[idx, "party"] = party
            resolved.at[idx, "prefill_source"] = source
            resolved.at[idx, "prefill_score"] = 1.0
            resolved.at[idx, "needs_review"] = False
            continue

        match = _resolve_against_eci(row.get("candidate", ""), references.get(ac_no, []))
        if match is not None:
            party, source, score = match
            resolved.at[idx, "party"] = party
            resolved.at[idx, "prefill_source"] = source
            resolved.at[idx, "prefill_score"] = score
            resolved.at[idx, "needs_review"] = False

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    resolved.to_csv(out_csv, index=False)
    if unresolved_out_csv is not None:
        write_priority_unmapped_party_rows(resolved, unresolved_out_csv)
    return resolved


def prefill_candidate_party_map(
    scaffold_csv: Path,
    results_csv: Path,
    out_csv: Path,
    min_score: float = 0.74,
) -> pd.DataFrame:
    scaffold = pd.read_csv(scaffold_csv)
    results = pd.read_csv(results_csv)
    scaffold["ac_no"] = pd.to_numeric(scaffold["ac_no"], errors="coerce").astype("Int64")
    results["ac_no"] = pd.to_numeric(results["ac_no"], errors="coerce").astype("Int64")

    if {"candidate", "party"}.issubset(results.columns):
        result_lookup = _candidate_result_lookup(results)
    else:
        result_lookup = _legacy_winner_runner_lookup(results)

    prefilled = scaffold.copy()
    if "party" not in prefilled.columns:
        prefilled["party"] = ""
    prefilled["party"] = prefilled["party"].fillna("")
    prefilled["prefill_source"] = ""
    prefilled["prefill_score"] = pd.NA

    for idx, row in prefilled.iterrows():
        if str(row.get("party", "")).strip():
            continue
        if bool(row.get("is_placeholder_candidate", False)) or bool(row.get("is_non_candidate_header", False)):
            continue
        ac_no = int(row["ac_no"])
        best: tuple[float, str, str, str] | None = None
        for ref_name, ref_party, source_label in result_lookup.get(ac_no, []):
            score = _match_score(row["candidate"], ref_name)
            if best is None or score > best[0]:
                best = (score, ref_name, ref_party, source_label)
        if best and best[0] >= min_score:
            prefilled.at[idx, "party"] = best[2]
            prefilled.at[idx, "prefill_source"] = f"{best[3]}:{best[1]}"
            prefilled.at[idx, "prefill_score"] = round(best[0], 3)
            prefilled.at[idx, "needs_review"] = False

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    prefilled.to_csv(out_csv, index=False)
    return prefilled
