from __future__ import annotations

from pathlib import Path

import pandas as pd


def parsed_ac_numbers(candidate_votes_csv: Path) -> set[int]:
    if not candidate_votes_csv.exists():
        return set()
    df = pd.read_csv(candidate_votes_csv, usecols=["ac_no"])
    return {int(value) for value in df["ac_no"].dropna().unique()}


def pdf_ac_numbers(pdf_dir: Path) -> set[int]:
    acs: set[int] = set()
    for path in pdf_dir.glob("*_Form20.pdf"):
        if path.name[:1].isdigit():
            acs.add(int(path.name.split("_", 1)[0]))
    return acs


def missing_parsed_acs(pdf_dir: Path, candidate_votes_csv: Path) -> list[int]:
    return sorted(pdf_ac_numbers(pdf_dir) - parsed_ac_numbers(candidate_votes_csv))

