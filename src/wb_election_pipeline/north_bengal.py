from __future__ import annotations

from pathlib import Path

import pandas as pd

# ACs 1-54 cover all North Bengal districts (Cooch Behar, Alipurduar, Jalpaiguri,
# Kalimpong, Darjeeling, Uttar Dinajpur, Dakshin Dinajpur, Malda).
NORTH_BENGAL_ACS: list[int] = list(range(1, 55))

ALLOWED_PARTIES = ["TMC", "BJP", "INC", "CPM", "ISF", "OTHER"]
NON_CANDIDATE_PATTERNS = (
    "SERIAL NO",
    "SL. NO",
    "POLLING STATION",
    "TOTAL",
    "VALID VOTES",
    "REJECTED",
    "TENDERED",
    "NOTA",
)


def _load_scope(scope_csv: Path) -> pd.DataFrame:
    scope = pd.read_csv(scope_csv)
    scope["ac_no"] = pd.to_numeric(scope["ac_no"], errors="coerce").astype("Int64")
    return scope


def build_scoped_candidate_votes(
    votes_csv: Path,
    quality_csv: Path,
    scope_csv: Path,
    out_csv: Path,
) -> pd.DataFrame:
    votes = pd.read_csv(votes_csv)
    quality = pd.read_csv(quality_csv)
    scope = _load_scope(scope_csv)

    votes["ac_no"] = pd.to_numeric(votes["ac_no"], errors="coerce").astype("Int64")
    quality["ac_no"] = pd.to_numeric(quality["ac_no"], errors="coerce").astype("Int64")
    votes["polling_station"] = votes["polling_station"].astype(str).str.strip()
    votes["candidate"] = votes["candidate"].astype(str).str.strip()
    votes["votes"] = pd.to_numeric(votes["votes"], errors="coerce").fillna(0).astype(int)

    scoped = votes.merge(scope, on="ac_no", how="inner")
    scoped = scoped.merge(
        quality[
            [
                "ac_no",
                "booths",
                "total_valid_coverage_pct",
                "placeholder_booth_pct",
                "booths_low_candidate_count",
                "booths_with_placeholders",
            ]
        ],
        on="ac_no",
        how="left",
    )
    scoped["is_placeholder_candidate"] = scoped["candidate"].str.contains(r"^candidate_col_", regex=True)
    scoped["candidate_needs_party_review"] = scoped["is_placeholder_candidate"]
    scoped["ac_quality_flag"] = ""
    scoped.loc[scoped["booths"].fillna(0) < 150, "ac_quality_flag"] += "low_booth_count;"
    scoped.loc[
        scoped["placeholder_booth_pct"].fillna(0) > 0.25,
        "ac_quality_flag",
    ] += "high_placeholder_rate;"
    scoped.loc[
        scoped["total_valid_coverage_pct"].fillna(0) < 0.25,
        "ac_quality_flag",
    ] += "low_total_valid_coverage;"
    scoped["form20_model_ready"] = (
        scoped["ac_quality_flag"].eq("")
        & ~scoped["is_placeholder_candidate"]
        & scoped["votes"].ge(0)
    )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    scoped.to_csv(out_csv, index=False)
    return scoped


def build_candidate_party_scaffold(votes_csv: Path, out_csv: Path) -> pd.DataFrame:
    votes = pd.read_csv(votes_csv)
    votes["ac_no"] = pd.to_numeric(votes["ac_no"], errors="coerce").astype("Int64")
    votes["candidate"] = votes["candidate"].astype(str).str.strip()
    scaffold = (
        votes.groupby(["ac_no", "district", "ac_name", "candidate"], dropna=False)
        .agg(
            candidate_votes_total=("votes", "sum"),
            booth_count=("polling_station", "nunique"),
            is_placeholder_candidate=("is_placeholder_candidate", "max"),
        )
        .reset_index()
        .sort_values(["ac_no", "candidate_votes_total"], ascending=[True, False])
    )
    scaffold["party"] = ""
    scaffold["allowed_parties"] = "|".join(ALLOWED_PARTIES)
    scaffold["is_non_candidate_header"] = scaffold["candidate"].str.upper().apply(
        lambda value: any(pattern in value for pattern in NON_CANDIDATE_PATTERNS)
    )
    scaffold["needs_review"] = True
    scaffold["notes"] = ""
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    scaffold.to_csv(out_csv, index=False)
    return scaffold


def build_booth_features(
    booth_party_shares_csv: Path,
    roll_booth_csv: Path | None,
    turnout_csv: Path | None,
    scope_csv: Path,
    out_csv: Path,
) -> pd.DataFrame:
    features = pd.read_csv(booth_party_shares_csv)
    scope = _load_scope(scope_csv)
    features["ac_no"] = pd.to_numeric(features["ac_no"], errors="coerce").astype("Int64")
    features["polling_station"] = features["polling_station"].astype(str).str.strip()
    features = features.merge(scope, on="ac_no", how="inner")

    if roll_booth_csv is not None and roll_booth_csv.exists():
        roll = pd.read_csv(roll_booth_csv)
        roll["ac_no"] = pd.to_numeric(roll["ac_no"], errors="coerce").astype("Int64")
        roll["part_no"] = roll["part_no"].astype(str).str.strip()
        if "registered_voters" in roll.columns and "year" in roll.columns:
            years = sorted(pd.to_numeric(roll["year"], errors="coerce").dropna().astype(int).unique())
            if len(years) == 1:
                year = years[0]
                roll = roll.rename(columns={"registered_voters": f"registered_voters_{year}"})
        features = features.merge(
            roll,
            left_on=["ac_no", "polling_station"],
            right_on=["ac_no", "part_no"],
            how="left",
        )
        features = _fill_roll_counts_by_base_part(features, roll)

    if turnout_csv is not None and turnout_csv.exists():
        turnout = pd.read_csv(turnout_csv)
        turnout["ac_no"] = pd.to_numeric(turnout["ac_no"], errors="coerce").astype("Int64")
        turnout["polling_station"] = turnout["polling_station"].astype(str).str.strip()
        features = features.merge(turnout, on=["ac_no", "polling_station"], how="left")

    features["has_party_features"] = features[["bjp_share", "tmc_share"]].notna().all(axis=1)
    if "old_roll_voters" in features.columns:
        features["has_roll_features"] = features[["old_roll_voters", "new_roll_voters"]].notna().all(axis=1)
    elif "registered_voters_2026" in features.columns:
        features["has_roll_features"] = features["registered_voters_2026"].notna()
    else:
        features["has_roll_features"] = False
    features["model_ready_booth"] = features["has_party_features"] & features["has_roll_features"]

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(out_csv, index=False)
    return features


def _base_part(value: object) -> str:
    match = pd.Series([str(value)]).str.extract(r"^\s*0*([0-9]+)", expand=False).iloc[0]
    return "" if pd.isna(match) else str(int(match))


def _fill_roll_counts_by_base_part(features: pd.DataFrame, roll: pd.DataFrame) -> pd.DataFrame:
    voter_col = next((column for column in ("registered_voters_2026", "registered_voters") if column in roll.columns), None)
    if voter_col is None:
        return features

    features = features.copy()
    features["polling_station_base_part"] = features["polling_station"].map(_base_part)

    roll_base = roll[["ac_no", "part_no", voter_col]].copy()
    roll_base["part_no_base"] = roll_base["part_no"].map(_base_part)
    roll_base = (
        roll_base.dropna(subset=[voter_col])
        .drop_duplicates(["ac_no", "part_no_base"])
        .rename(columns={voter_col: "_base_registered_voters_2026"})
    )

    features = features.merge(
        roll_base[["ac_no", "part_no_base", "_base_registered_voters_2026"]],
        left_on=["ac_no", "polling_station_base_part"],
        right_on=["ac_no", "part_no_base"],
        how="left",
    )
    if "registered_voters_2026" not in features.columns:
        features["registered_voters_2026"] = pd.NA
    if "roll_join_method" not in features.columns:
        features["roll_join_method"] = pd.NA
    features.loc[
        features["registered_voters_2026"].notna() & features["roll_join_method"].isna(),
        "roll_join_method",
    ] = "exact"

    features["_base_group_total_votes"] = features.groupby(
        ["ac_no", "polling_station_base_part"], dropna=False
    )["total_votes"].transform("sum")
    features["_base_group_size"] = features.groupby(
        ["ac_no", "polling_station_base_part"], dropna=False
    )["polling_station"].transform("count")

    can_allocate = (
        features["_base_registered_voters_2026"].notna()
        & features["polling_station_base_part"].ne("")
        & features["_base_group_total_votes"].gt(0)
    )
    allocated = (
        features["_base_registered_voters_2026"]
        * pd.to_numeric(features["total_votes"], errors="coerce").fillna(0)
        / features["_base_group_total_votes"]
    )
    needs_fill = features["registered_voters_2026"].isna()
    split_group = features["_base_group_size"].gt(1)
    features.loc[can_allocate & (needs_fill | split_group), "registered_voters_2026"] = allocated
    features.loc[can_allocate & (needs_fill | split_group), "roll_join_method"] = "base_part_allocated"

    return features.drop(
        columns=[
            "part_no_base",
            "_base_registered_voters_2026",
            "_base_group_total_votes",
            "_base_group_size",
        ],
        errors="ignore",
    )
