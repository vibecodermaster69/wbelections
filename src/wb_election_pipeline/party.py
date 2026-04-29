from __future__ import annotations

from pathlib import Path

import pandas as pd


def normalize_party(value: object) -> str:
    if value is None or pd.isna(value):
        return "OTHER"
    text = " ".join(str(value).upper().replace(".", " ").split())
    aliases = {
        "AITC": "TMC",
        "ALL INDIA TRINAMOOL CONGRESS": "TMC",
        "TMC": "TMC",
        "TRINAMOOL CONGRESS": "TMC",
        "BHARATIYA JANATA PARTY": "BJP",
        "BJP": "BJP",
    }
    return aliases.get(text, text or "OTHER")


def load_candidate_party_map(path: Path) -> pd.DataFrame:
    mapping = pd.read_csv(path)
    required = {"ac_no", "candidate", "party"}
    missing = required - set(mapping.columns)
    if missing:
        raise ValueError(f"Party map missing columns: {sorted(missing)}")
    mapping = mapping.copy()
    mapping["candidate_key"] = mapping["candidate"].map(normalize_candidate_name)
    mapping["normalized_party"] = mapping["party"].map(normalize_party)
    return mapping[["ac_no", "candidate_key", "normalized_party"]]


def normalize_candidate_name(value: object) -> str:
    return " ".join(str(value).upper().replace(".", " ").split())


def aggregate_party_shares(votes_csv: Path, party_map_csv: Path, out_csv: Path) -> pd.DataFrame:
    votes = pd.read_csv(votes_csv)
    mapping = load_candidate_party_map(party_map_csv)
    votes = votes.copy()
    votes["ac_name"] = votes.get("ac_name", "").fillna("")
    votes["polling_station"] = votes["polling_station"].astype(str).str.strip()
    votes["candidate_key"] = votes["candidate"].map(normalize_candidate_name)
    merged = votes.merge(mapping, on=["ac_no", "candidate_key"], how="left")
    merged["normalized_party"] = merged["normalized_party"].fillna("OTHER")

    grouped = (
        merged.groupby(["ac_no", "ac_name", "polling_station", "normalized_party"], dropna=False)[
            "votes"
        ]
        .sum()
        .reset_index()
    )
    pivot = (
        grouped.set_index(["ac_no", "ac_name", "polling_station", "normalized_party"])["votes"]
        .unstack("normalized_party", fill_value=0)
        .reset_index()
    )

    for party in ["BJP", "TMC", "OTHER"]:
        if party not in pivot.columns:
            pivot[party] = 0
    party_cols = [col for col in pivot.columns if col not in {"ac_no", "ac_name", "polling_station"}]
    pivot["total_votes"] = pivot[party_cols].sum(axis=1)
    pivot["bjp_share"] = pivot["BJP"] / pivot["total_votes"].where(pivot["total_votes"] > 0)
    pivot["tmc_share"] = pivot["TMC"] / pivot["total_votes"].where(pivot["total_votes"] > 0)
    pivot["other_share"] = pivot["OTHER"] / pivot["total_votes"].where(pivot["total_votes"] > 0)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pivot.to_csv(out_csv, index=False)
    return pivot
