from __future__ import annotations

from pathlib import Path
import re

import pandas as pd

from .parse_form20 import _is_markdown_separator, _markdown_tables

ROLL_COLUMNS = [
    "year",
    "ac_no",
    "part_no",
    "serial_no",
    "name",
    "relative_name",
    "gender",
    "age",
    "epic_optional",
    "source_file",
]

ROLL_COUNT_COLUMNS = [
    "year",
    "ac_no",
    "part_no",
    "registered_voters",
    "male_voters",
    "female_voters",
    "parsed_rows",
    "serial_min",
    "serial_max",
    "serial_gaps",
    "source_file",
]

ROLL_SUMMARY_COUNT_COLUMNS = [
    "year",
    "ac_no",
    "part_no",
    "registered_voters",
    "male_voters",
    "female_voters",
    "source_file",
    "parse_method",
    "quality_flag",
]

BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def _clean(value: object) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def _normalize_digits(value: str) -> str:
    return value.translate(BENGALI_DIGITS).translate(DEVANAGARI_DIGITS)


def _filename_ac_part(path: Path) -> tuple[int | None, str | None]:
    match = re.search(r"AC0*([0-9]+)PART0*([0-9]+)", path.stem, re.I)
    if match:
        return int(match.group(1)), str(int(match.group(2)))
    filename_ac = int(path.name.split("_", 1)[0]) if path.name[:1].isdigit() else None
    return filename_ac, None


def _find_col(header: list[str], patterns: tuple[str, ...]) -> int | None:
    for idx, cell in enumerate(header):
        normalized = re.sub(r"[^A-Z0-9]", "", cell.upper())
        if any(pattern in normalized for pattern in patterns):
            return idx
    return None


def parse_roll_markdown_file(path: Path, year: int, ac_no: int | None = None, part_no: str | None = None) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8")
    filename_ac, filename_part = _filename_ac_part(path)
    ac = ac_no or filename_ac
    default_part = part_no or filename_part or path.stem
    records: list[dict[str, object]] = []

    for table in _markdown_tables(text):
        header = table[0]
        rows = table[2:] if len(table) > 1 and _is_markdown_separator(table[1]) else table[1:]
        serial_col = _find_col(header, ("SERIALNO", "SLNO", "SNO"))
        name_col = _find_col(header, ("NAME", "ELECTORNAME"))
        relative_col = _find_col(
            header,
            ("RELATIVENAME", "FATHERNAME", "MOTHERNAME", "HUSBANDNAME", "RELATIV"),
        )
        gender_col = _find_col(header, ("GENDER", "SEX"))
        age_col = _find_col(header, ("AGE",))
        epic_col = _find_col(header, ("EPIC", "VOTERID", "CARDNO"))
        part_col = _find_col(header, ("PARTNO", "PARTNUMBER"))

        # Gemini roll OCR may preserve Bengali headers, or return translated
        # but inconsistent headers. The table layout is still stable:
        # serial, blank/part, name, relation type, relative name, gender, age, epic.
        positional_roll = False
        if serial_col is None and name_col is None and len(header) >= 8:
            serial_col = 0
            name_col = 2
            relative_col = 4
            gender_col = 5
            age_col = 6
            epic_col = 7
            positional_roll = True

        if serial_col is None or name_col is None:
            continue
        for row in rows:
            if len(row) <= max(serial_col, name_col):
                continue
            serial = _normalize_digits(_clean(row[serial_col]))
            name = _clean(row[name_col])
            if not serial or not name:
                continue
            if not re.search(r"\d", serial):
                continue
            if positional_roll and (name.startswith("**") or name.isdigit()):
                continue
            records.append(
                {
                    "year": year,
                    "ac_no": ac,
                    "part_no": (
                        _normalize_digits(_clean(row[part_col])) or default_part
                        if part_col is not None and part_col < len(row)
                        else default_part
                    ),
                    "serial_no": serial,
                    "name": name,
                    "relative_name": _clean(row[relative_col]) if relative_col is not None and relative_col < len(row) else "",
                    "gender": _clean(row[gender_col]) if gender_col is not None and gender_col < len(row) else "",
                    "age": _normalize_digits(_clean(row[age_col])) if age_col is not None and age_col < len(row) else "",
                    "epic_optional": _clean(row[epic_col]) if epic_col is not None and epic_col < len(row) else "",
                    "source_file": path.name,
                }
            )
    return pd.DataFrame(records, columns=ROLL_COLUMNS)


def parse_roll_markdown_dir(markdown_dir: Path, year: int, out_csv: Path) -> pd.DataFrame:
    frames = []
    failures: list[dict[str, str]] = []
    for path in sorted(markdown_dir.glob("*.md")):
        try:
            parsed = parse_roll_markdown_file(path, year=year)
        except Exception as exc:
            failures.append({"source_file": path.name, "error": str(exc)})
            continue
        if parsed.empty:
            failures.append({"source_file": path.name, "error": "No voter roll rows parsed"})
        else:
            frames.append(parsed)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=ROLL_COLUMNS)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_csv, index=False)
    if failures:
        pd.DataFrame(failures).to_csv(out_csv.with_suffix(".failures.csv"), index=False)
    return combined


def parse_roll_count_markdown_file(path: Path, year: int, ac_no: int | None = None, part_no: str | None = None) -> pd.DataFrame:
    rows = parse_roll_markdown_file(path, year=year, ac_no=ac_no, part_no=part_no)
    if rows.empty:
        return pd.DataFrame(columns=ROLL_COUNT_COLUMNS)
    rows["serial_no_num"] = pd.to_numeric(rows["serial_no"].map(lambda value: _normalize_digits(str(value))), errors="coerce")
    rows = rows.dropna(subset=["serial_no_num"]).copy()
    if rows.empty:
        return pd.DataFrame(columns=ROLL_COUNT_COLUMNS)
    rows["serial_no_num"] = rows["serial_no_num"].astype(int)

    grouped = (
        rows.groupby(["year", "ac_no", "part_no", "source_file"], dropna=False)
        .agg(
            parsed_rows=("serial_no_num", "count"),
            serial_min=("serial_no_num", "min"),
            serial_max=("serial_no_num", "max"),
        )
        .reset_index()
    )
    grouped["registered_voters"] = grouped["serial_max"]
    grouped["male_voters"] = pd.NA
    grouped["female_voters"] = pd.NA
    grouped["serial_gaps"] = (grouped["serial_max"] - grouped["serial_min"] + 1 - grouped["parsed_rows"]).clip(lower=0)
    return grouped[ROLL_COUNT_COLUMNS]


def parse_roll_count_markdown_dir(markdown_dir: Path, year: int, out_csv: Path) -> pd.DataFrame:
    frames = []
    failures: list[dict[str, str]] = []
    for path in sorted(markdown_dir.rglob("*.md")):
        try:
            parsed = parse_roll_count_markdown_file(path, year=year)
        except Exception as exc:
            failures.append({"source_file": str(path), "error": str(exc)})
            continue
        if parsed.empty:
            failures.append({"source_file": str(path), "error": "No voter roll serials parsed"})
        else:
            frames.append(parsed)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=ROLL_COUNT_COLUMNS)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_csv, index=False)
    if failures:
        pd.DataFrame(failures).to_csv(out_csv.with_suffix(".failures.csv"), index=False)
    return combined


def _dedupe_positioned_chars(chars: list[dict[str, object]], x_tolerance: float = 1.0) -> list[dict[str, object]]:
    """Remove overprinted duplicate PDF glyphs at almost identical positions."""
    deduped: list[dict[str, object]] = []
    for char in sorted(chars, key=lambda item: (float(item["x0"]), float(item["y0"]))):
        if deduped and abs(float(char["x0"]) - float(deduped[-1]["x0"])) <= x_tolerance:
            continue
        deduped.append(char)
    return deduped


def _normalize_digit_mask(mask: object, size: int = 32) -> object:
    import numpy as np
    from PIL import Image

    arr = np.asarray(mask, dtype=bool)
    ys, xs = np.where(arr)
    if len(xs) == 0:
        return np.zeros((size, size), dtype=bool)
    y0, y1 = max(0, int(ys.min()) - 1), min(arr.shape[0], int(ys.max()) + 2)
    x0, x1 = max(0, int(xs.min()) - 1), min(arr.shape[1], int(xs.max()) + 2)
    arr = arr[y0:y1, x0:x1]
    height, width = arr.shape
    scale = min((size - 4) / max(width, 1), (size - 4) / max(height, 1))
    new_width = max(1, int(round(width * scale)))
    new_height = max(1, int(round(height * scale)))
    image = Image.fromarray((~arr * 255).astype("uint8"))
    image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    resized = np.asarray(image) < 180
    canvas = np.zeros((size, size), dtype=bool)
    top = (size - new_height) // 2
    left = (size - new_width) // 2
    canvas[top : top + new_height, left : left + new_width] = resized
    return canvas


def _digit_mask_from_crop(image: object) -> object:
    import numpy as np

    gray = image.convert("L")
    return _normalize_digit_mask(np.asarray(gray) < 180)


def _render_page_image(page: object, zoom: int = 4) -> object:
    import fitz
    from PIL import Image

    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)


def _crop_char_image(rendered_page: object, char: dict[str, object], zoom: int = 4) -> object:
    pad = 1.5
    return rendered_page.crop(
        (
            int((float(char["x0"]) - pad) * zoom),
            int((float(char["y0"]) - pad) * zoom),
            int((float(char["x1"]) + pad) * zoom),
            int((float(char["y1"]) + pad) * zoom),
        )
    )


def _page_chars(page: object) -> list[dict[str, object]]:
    chars: list[dict[str, object]] = []
    for span in page.get_texttrace():
        font = str(span.get("font", ""))
        for glyph in span.get("chars", []):
            _unicode, glyph_id, _origin, bbox = glyph
            x0, y0, x1, y1 = bbox
            chars.append(
                {
                    "x0": float(x0),
                    "y0": float(y0),
                    "x1": float(x1),
                    "y1": float(y1),
                    "width": float(x1 - x0),
                    "glyph_id": int(glyph_id),
                    "font": font,
                }
            )
    return chars


def _chars_in_region(
    chars: list[dict[str, object]],
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    min_width: float = 4.0,
) -> list[dict[str, object]]:
    selected = [
        char
        for char in chars
        if x0 <= float(char["x0"]) < x1
        and y0 <= float(char["y0"]) < y1
        and float(char["width"]) >= min_width
    ]
    return _dedupe_positioned_chars(selected)


def _add_digit_templates(
    templates: dict[str, list[object]],
    rendered_page: object,
    chars: list[dict[str, object]],
    digits: str,
) -> None:
    if len(chars) != len(digits):
        return
    for char, digit in zip(chars, digits):
        if not digit.isdigit():
            continue
        templates.setdefault(digit, []).append(_digit_mask_from_crop(_crop_char_image(rendered_page, char)))


def _add_known_digit_glyphs(
    known: dict[str, dict[int, str]],
    chars: list[dict[str, object]],
    pattern: str,
) -> None:
    if len(chars) != len(pattern):
        return
    for char, digit in zip(chars, pattern):
        if not digit.isdigit():
            continue
        font = str(char["font"])
        glyph_id = int(char["glyph_id"])
        current = known.setdefault(font, {}).get(glyph_id)
        if current is None or current == digit:
            known.setdefault(font, {})[glyph_id] = digit


def _train_roll_digit_templates(paths: list[Path], max_pages: int | None = None) -> dict[str, list[object]]:
    """Build digit templates from rendered glyphs whose values are known from PDF metadata fields.

    The voter-roll PDFs use custom embedded font encodings, but visible digit shapes
    are stable on the rendered page. We learn those shapes from known fields:
    revision year/date and the part number embedded in the filename.
    """
    import fitz

    templates: dict[str, list[object]] = {}
    for idx, path in enumerate(paths):
        if max_pages is not None and idx >= max_pages:
            break
        ac_no, part_no = _filename_ac_part(path)
        try:
            with fitz.open(path) as doc:
                if doc.page_count == 0:
                    continue
                page = doc[0]
                chars = _page_chars(page)
                rendered_page = _render_page_image(page)
                width = float(page.rect.width)
                height = float(page.rect.height)

                # Date line is visually "01-01-2002" in these roll PDFs.
                date_chars = _chars_in_region(
                    chars,
                    x0=width * 0.20,
                    y0=height * 0.20,
                    x1=width * 0.40,
                    y1=height * 0.25,
                    min_width=4.0,
                )
                if len(date_chars) >= 10:
                    _add_digit_templates(templates, rendered_page, date_chars[:10], "01-01-2002")

                year_chars = _chars_in_region(
                    chars,
                    x0=width * 0.25,
                    y0=height * 0.17,
                    x1=width * 0.38,
                    y1=height * 0.22,
                    min_width=4.0,
                )
                if len(year_chars) >= 4:
                    _add_digit_templates(templates, rendered_page, year_chars[-4:], "2002")

                if part_no:
                    part_digits = str(int(part_no))
                    top_part_chars = _chars_in_region(
                        chars,
                        x0=width * 0.80,
                        y0=height * 0.07,
                        x1=width * 0.93,
                        y1=height * 0.12,
                        min_width=4.0,
                    )
                    if len(top_part_chars) >= len(part_digits):
                        _add_digit_templates(templates, rendered_page, top_part_chars[-len(part_digits) :], part_digits)

                if ac_no is not None:
                    ac_digits = str(int(ac_no))
                    ac_chars = _chars_in_region(
                        chars,
                        x0=width * 0.20,
                        y0=height * 0.08,
                        x1=width * 0.32,
                        y1=height * 0.13,
                        min_width=4.0,
                    )
                    if len(ac_chars) >= len(ac_digits):
                        _add_digit_templates(templates, rendered_page, ac_chars[-len(ac_digits) :], ac_digits)
        except Exception:
            continue
    return {digit: masks for digit, masks in templates.items() if masks}


def _summary_digit_chars_by_column(page: object, chars: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    width = float(page.rect.width)
    height = float(page.rect.height)
    row_y0 = height * 0.92
    row_y1 = height * 0.98
    columns = {
        "male_voters": (width * 0.59, width * 0.72),
        "female_voters": (width * 0.72, width * 0.83),
        "registered_voters": (width * 0.83, width * 0.93),
    }
    return {
        name: _chars_in_region(chars, x0=col_x0, y0=row_y0, x1=col_x1, y1=row_y1, min_width=4.0)
        for name, (col_x0, col_x1) in columns.items()
    }


def _collect_roll_known_glyphs_and_equations(
    paths: list[Path],
    max_pages: int | None = None,
) -> tuple[dict[str, dict[int, str]], dict[str, list[tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]]]]:
    import fitz

    known: dict[str, dict[int, str]] = {}
    equations: dict[str, list[tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]]] = {}
    for idx, path in enumerate(paths):
        if max_pages is not None and idx >= max_pages:
            break
        _ac_no, part_no = _filename_ac_part(path)
        try:
            with fitz.open(path) as doc:
                if doc.page_count == 0:
                    continue
                page = doc[0]
                chars = _page_chars(page)
                width = float(page.rect.width)
                height = float(page.rect.height)

                if part_no:
                    part_digits = str(int(part_no))
                    top_part_chars = _chars_in_region(
                        chars,
                        x0=width * 0.80,
                        y0=height * 0.07,
                        x1=width * 0.93,
                        y1=height * 0.12,
                        min_width=4.0,
                    )
                    if len(top_part_chars) >= len(part_digits):
                        _add_known_digit_glyphs(known, top_part_chars[-len(part_digits) :], part_digits)

                summary = _summary_digit_chars_by_column(page, chars)
                if not all(summary.values()):
                    continue
                fonts = {str(char["font"]) for col in summary.values() for char in col}
                if len(fonts) != 1:
                    continue
                font = fonts.pop()
                equations.setdefault(font, []).append(
                    (
                        tuple(int(char["glyph_id"]) for char in summary["male_voters"]),
                        tuple(int(char["glyph_id"]) for char in summary["female_voters"]),
                        tuple(int(char["glyph_id"]) for char in summary["registered_voters"]),
                    )
                )
        except Exception:
            continue
    return known, equations


def _solve_roll_digit_maps(
    known: dict[str, dict[int, str]],
    equations: dict[str, list[tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]]],
) -> dict[str, dict[int, str]]:
    from itertools import permutations

    digit_maps: dict[str, dict[int, str]] = {}

    def decode(token: tuple[int, ...], mapping: dict[int, str]) -> int:
        return int("".join(mapping[glyph] for glyph in token))

    def is_consistent(base: dict[int, str], candidate: dict[int, str]) -> bool:
        reverse = {digit: glyph for glyph, digit in base.items()}
        for glyph, digit in candidate.items():
            if glyph in base and base[glyph] != digit:
                return False
            if digit in reverse and reverse[digit] != glyph:
                return False
        return True

    def merge(base: dict[int, str], candidate: dict[int, str]) -> dict[int, str]:
        merged = dict(base)
        merged.update(candidate)
        return merged

    def equation_candidates(
        equation: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]],
        base: dict[int, str],
    ) -> list[dict[int, str]]:
        male_token, female_token, total_token = equation
        glyphs = sorted({glyph for token in equation for glyph in token if glyph not in base})
        remaining_digits = sorted(set("0123456789") - set(base.values()))
        candidates: list[dict[int, str]] = []
        if len(glyphs) > len(remaining_digits):
            return candidates
        for digits in permutations(remaining_digits, len(glyphs)):
            candidate = dict(zip(glyphs, digits))
            mapping = merge(base, candidate)
            male = decode(male_token, mapping)
            female = decode(female_token, mapping)
            total = decode(total_token, mapping)
            if male + female == total and 100 <= male <= 900 and 100 <= female <= 900 and 200 <= total <= 1500:
                candidates.append(candidate)
        return candidates

    def solve_exact(
        font_equations: list[tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]],
        base: dict[int, str],
    ) -> dict[int, str] | None:
        candidate_sets = [(equation, equation_candidates(equation, base)) for equation in font_equations]
        candidate_sets = [(equation, candidates) for equation, candidates in candidate_sets if candidates]
        if not candidate_sets:
            return None
        candidate_sets.sort(key=lambda item: len(item[1]))

        best: dict[int, str] | None = None

        def backtrack(index: int, mapping: dict[int, str]) -> bool:
            nonlocal best
            if index == len(candidate_sets):
                best = mapping
                return True
            _equation, candidates = candidate_sets[index]
            for candidate in candidates:
                if not is_consistent(mapping, candidate):
                    continue
                if backtrack(index + 1, merge(mapping, candidate)):
                    return True
            return False

        backtrack(0, dict(base))
        return best

    for font, font_equations in equations.items():
        if font in digit_maps:
            continue
        # Use only clean header hints (currently part number), then constrain
        # the remaining glyphs through male + female = total equations.
        base = dict(known.get(font, {}))
        exact = solve_exact(font_equations, base)
        if exact is not None:
            digit_maps[font] = exact
            continue

        glyphs = sorted({glyph for equation in font_equations for token in equation for glyph in token})
        unknown_glyphs = [glyph for glyph in glyphs if glyph not in base]
        remaining_digits = sorted(set("0123456789") - set(base.values()))
        if len(unknown_glyphs) > len(remaining_digits):
            continue

        best_mapping: dict[int, str] | None = None
        best_score = -1
        best_plausible = -1
        for digits in permutations(remaining_digits, len(unknown_glyphs)):
            mapping = dict(base)
            mapping.update(dict(zip(unknown_glyphs, digits)))
            score = 0
            plausible = 0
            for male_token, female_token, total_token in font_equations:
                try:
                    male = decode(male_token, mapping)
                    female = decode(female_token, mapping)
                    total = decode(total_token, mapping)
                except KeyError:
                    continue
                if 100 <= male <= 900 and 100 <= female <= 900 and 200 <= total <= 1500:
                    plausible += 1
                if male + female == total:
                    score += 1
            if (score, plausible) > (best_score, best_plausible):
                best_score = score
                best_plausible = plausible
                best_mapping = mapping
        if best_mapping is not None:
            digit_maps[font] = best_mapping
    return digit_maps


def _classify_digit(mask: object, templates: dict[str, list[object]]) -> tuple[str, float]:
    import numpy as np

    best_digit = ""
    best_score = -1.0
    for digit, digit_templates in templates.items():
        for template in digit_templates:
            intersection = np.logical_and(mask, template).sum()
            union = np.logical_or(mask, template).sum()
            score = float(intersection / union) if union else 0.0
            if score > best_score:
                best_digit = digit
                best_score = score
    return best_digit, best_score


def _decode_digit_chars(
    rendered_page: object,
    chars: list[dict[str, object]],
    templates: dict[str, list[object]],
    digit_maps: dict[str, dict[int, str]] | None = None,
) -> tuple[str, float]:
    if digit_maps and chars:
        fonts = {str(char["font"]) for char in chars}
        if len(fonts) == 1:
            font = fonts.pop()
            mapping = digit_maps.get(font)
            if mapping and all(int(char["glyph_id"]) in mapping for char in chars):
                return "".join(mapping[int(char["glyph_id"])] for char in chars), 1.0
    direct = _decode_stable_roll_digit_font(chars)
    if direct:
        return direct, 1.0

    decoded: list[str] = []
    scores: list[float] = []
    for char in chars:
        mask = _digit_mask_from_crop(_crop_char_image(rendered_page, char))
        digit, score = _classify_digit(mask, templates)
        if digit:
            decoded.append(digit)
            scores.append(score)
    return "".join(decoded), (min(scores) if scores else 0.0)


def _decode_stable_roll_digit_font(chars: list[dict[str, object]]) -> str | None:
    return None


def parse_roll_summary_count_pdf_file(
    path: Path,
    year: int,
    templates: dict[str, list[object]],
    digit_maps: dict[str, dict[int, str]] | None = None,
) -> pd.DataFrame:
    import fitz

    ac_no, part_no = _filename_ac_part(path)
    if ac_no is None or part_no is None:
        return pd.DataFrame(columns=ROLL_SUMMARY_COUNT_COLUMNS)

    with fitz.open(path) as doc:
        if doc.page_count == 0:
            return pd.DataFrame(columns=ROLL_SUMMARY_COUNT_COLUMNS)
        registered_voters = _count_serial_rows_in_roll_pdf(doc)
        if registered_voters:
            return pd.DataFrame(
                [
                    {
                        "year": year,
                        "ac_no": ac_no,
                        "part_no": part_no,
                        "registered_voters": registered_voters,
                        "male_voters": pd.NA,
                        "female_voters": pd.NA,
                        "source_file": str(path),
                        "parse_method": "pdf_serial_row_count",
                        "quality_flag": "ok" if registered_voters <= 2000 else "implausible_total",
                    }
                ],
                columns=ROLL_SUMMARY_COUNT_COLUMNS,
            )
        page = doc[0]
        chars = _page_chars(page)
        rendered_page = _render_page_image(page)
        columns = _summary_digit_chars_by_column(page, chars)
        values: dict[str, int | None] = {}
        scores: list[float] = []
        for name, digit_chars in columns.items():
            decoded, score = _decode_digit_chars(rendered_page, digit_chars, templates, digit_maps=digit_maps)
            values[name] = int(decoded) if decoded.isdigit() else None
            if score:
                scores.append(score)

    male = values.get("male_voters")
    female = values.get("female_voters")
    summary_total = values.get("registered_voters")
    total = registered_voters or summary_total
    quality_flag = "ok"
    if total is None or total <= 0:
        quality_flag = "missing_count"
    elif summary_total is not None and summary_total != total:
        quality_flag = "summary_mismatch"
    elif male is not None and female is not None and male + female != total:
        quality_flag = "gender_sum_mismatch"
    elif total <= 0 or total > 2000:
        quality_flag = "implausible_total"
    elif scores and min(scores) < 0.45:
        quality_flag = "low_digit_confidence"

    return pd.DataFrame(
        [
            {
                "year": year,
                "ac_no": ac_no,
                "part_no": part_no,
                "registered_voters": total,
                "male_voters": male if male is not None and female is not None and male + female == total else pd.NA,
                "female_voters": female if male is not None and female is not None and male + female == total else pd.NA,
                "source_file": str(path),
                "parse_method": "pdf_serial_row_count",
                "quality_flag": quality_flag,
            }
        ],
        columns=ROLL_SUMMARY_COUNT_COLUMNS,
    )


def _count_serial_rows_in_roll_pdf(doc: object) -> int:
    total = 0
    for page_index in range(1, doc.page_count):
        page = doc[page_index]
        ys: list[float] = []
        for span in page.get_texttrace():
            for glyph in span.get("chars", []):
                _unicode, _glyph_id, _origin, bbox = glyph
                x0, y0, x1, _y1 = bbox
                width = x1 - x0
                if 45 <= x0 <= 120 and 130 <= y0 <= 790 and width >= 2.0:
                    ys.append(float(y0))
        if not ys:
            continue
        groups: list[list[float]] = []
        for y in sorted(ys):
            if not groups or abs(y - groups[-1][-1]) > 5:
                groups.append([y])
            else:
                groups[-1].append(y)
        total += len(groups)
    return total


def parse_roll_summary_count_pdf_dir(
    pdf_dir: Path,
    year: int,
    out_csv: Path,
    recursive: bool = True,
    template_scan_limit: int | None = None,
) -> pd.DataFrame:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    paths = sorted(pdf_dir.glob(pattern))
    templates: dict[str, list[object]] = {}
    digit_maps: dict[str, dict[int, str]] = {}

    frames = []
    failures: list[dict[str, str]] = []
    for path in paths:
        try:
            parsed = parse_roll_summary_count_pdf_file(path, year=year, templates=templates, digit_maps=digit_maps)
        except Exception as exc:
            failures.append({"source_file": str(path), "error": str(exc)})
            continue
        if parsed.empty:
            failures.append({"source_file": str(path), "error": "No roll summary count parsed"})
        else:
            frames.append(parsed)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=ROLL_SUMMARY_COUNT_COLUMNS)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_csv, index=False)
    if failures:
        pd.DataFrame(failures).to_csv(out_csv.with_suffix(".failures.csv"), index=False)
    return combined
