from __future__ import annotations

from pathlib import Path

import pandas as pd


def run_quality_checks(
    votes_csv: Path,
    coverage_csv: Path,
    ac_summary_out: Path,
    booth_issues_out: Path,
    scope_csv: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    votes = pd.read_csv(votes_csv)
    coverage = pd.read_csv(coverage_csv)

    votes["ac_no"] = pd.to_numeric(votes["ac_no"], errors="coerce").astype("Int64")
    votes["polling_station"] = votes["polling_station"].astype(str).str.strip()
    votes["candidate"] = votes["candidate"].astype(str).str.strip()
    votes["votes"] = pd.to_numeric(votes["votes"], errors="coerce")
    for col in ["total_valid_votes", "rejected_votes", "nota_votes", "total_votes_cast"]:
        if col in votes.columns:
            votes[col] = pd.to_numeric(votes[col], errors="coerce")
        else:
            votes[col] = pd.NA

    if scope_csv is not None:
        scope = pd.read_csv(scope_csv)
        scope["ac_no"] = pd.to_numeric(scope["ac_no"], errors="coerce").astype("Int64")
        votes = votes.merge(scope, on="ac_no", how="inner")
        coverage = coverage.merge(scope, on="ac_no", how="inner")

    booth = (
        votes.groupby(["ac_no", "polling_station"], dropna=False)
        .agg(
            row_count=("votes", "size"),
            candidate_count=("candidate", "nunique"),
            candidate_vote_sum=("votes", "sum"),
            total_valid_votes=("total_valid_votes", "max"),
            total_votes_cast=("total_votes_cast", "max"),
            placeholder_candidates=(
                "candidate",
                lambda s: int(s.str.contains(r"^candidate_col_", regex=True).sum()),
            ),
        )
        .reset_index()
    )
    booth["has_total_valid"] = booth["total_valid_votes"].notna()
    booth["candidate_sum_gt_total_valid"] = booth["has_total_valid"] & (
        booth["candidate_vote_sum"] > booth["total_valid_votes"] * 1.02
    )
    booth["candidate_sum_lt_total_valid"] = booth["has_total_valid"] & (
        booth["candidate_vote_sum"] < booth["total_valid_votes"] * 0.80
    )
    booth["low_candidate_count"] = booth["candidate_count"] < 2
    booth["high_candidate_count"] = booth["candidate_count"] > 20
    booth["has_placeholder_candidate"] = booth["placeholder_candidates"] > 0

    issue_cols = [
        "candidate_sum_gt_total_valid",
        "candidate_sum_lt_total_valid",
        "low_candidate_count",
        "high_candidate_count",
        "has_placeholder_candidate",
    ]
    issues = booth[booth[issue_cols].any(axis=1)].copy()
    ac_quality = (
        booth.groupby("ac_no", dropna=False)
        .agg(
            booths=("polling_station", "nunique"),
            booth_candidate_rows=("row_count", "sum"),
            avg_candidates_per_booth=("candidate_count", "mean"),
            booths_with_total_valid=("has_total_valid", "sum"),
            booths_sum_gt_total=("candidate_sum_gt_total_valid", "sum"),
            booths_sum_lt_total=("candidate_sum_lt_total_valid", "sum"),
            booths_low_candidate_count=("low_candidate_count", "sum"),
            booths_high_candidate_count=("high_candidate_count", "sum"),
            booths_with_placeholders=("has_placeholder_candidate", "sum"),
        )
        .reset_index()
    )
    ac_quality["total_valid_coverage_pct"] = (
        ac_quality["booths_with_total_valid"] / ac_quality["booths"]
    ).round(3)
    ac_quality["placeholder_booth_pct"] = (
        ac_quality["booths_with_placeholders"] / ac_quality["booths"]
    ).round(3)

    if scope_csv is not None:
        scope = pd.read_csv(scope_csv)
        ac_quality = ac_quality.merge(scope, on="ac_no", how="left")

    ac_summary_out.parent.mkdir(parents=True, exist_ok=True)
    ac_quality.to_csv(ac_summary_out, index=False)
    issues.to_csv(booth_issues_out, index=False)
    return ac_quality, issues


# ---------------------------------------------------------------------------
# AC-level electors (WB 2021 reference) for per-booth vote-share thresholds.
# Source: ECI Detailed Results PDF, all 54 North Bengal ACs.
# ---------------------------------------------------------------------------
_NB_AC_ELECTORS: dict[int, int] = {
    1: 226465, 2: 248022, 3: 282988, 4: 233839, 5: 285260, 6: 290568, 7: 299251,
    8: 245040, 9: 234311, 10: 272924, 11: 247425, 12: 260652, 13: 254554, 14: 212651,
    15: 263118, 16: 264265, 17: 262500, 18: 244163, 19: 310354, 20: 255570,
    21: 237305, 22: 211896, 23: 246663, 24: 236477, 25: 287565, 26: 228406,
    27: 240496, 28: 247764, 29: 219728, 30: 224633, 31: 233378, 32: 262583,
    33: 265318, 34: 282575, 35: 198780, 36: 229362, 37: 219921, 38: 203986,
    39: 180390, 40: 220236, 41: 224040, 42: 228189, 43: 249557, 44: 267096,
    45: 249402, 46: 252487, 47: 231907, 48: 282451, 49: 253353, 50: 245962,
    51: 275296, 52: 196324, 53: 251186, 54: 246956,
}


def run_party_share_quality_checks(
    party_shares_csv: Path,
    out_csv: Path,
    ac_no_col: str = "ac_no",
    station_col: str = "polling_station",
) -> pd.DataFrame:
    """Flag booths in the party-shares CSV for anomalous vote counts or shares.

    Flags produced
    --------------
    flag_phantom_booth
        total_votes exceeds 5 % of the full AC's registered electors.  These
        rows are almost certainly AC-level summary totals that were mistakenly
        parsed as individual booth rows.
    flag_high_votes
        total_votes > 2 000.  A valid polling booth rarely exceeds this in NB.
    flag_low_votes
        total_votes < 10 (but > 0).  Likely a partial-parse or auxiliary row.
    flag_single_party_monopoly
        One named party holds ≥ 99 % of the booth's valid votes and
        total_votes > 100.  Includes tmc_monopoly and bjp_monopoly sub-flags.
    flag_zero_named_parties
        BJP = 0 AND TMC = 0 and total_votes ≥ 200.  Indicates that no
        BJP/TMC candidate was recognised by the party map for this booth.
        This is primarily a *mapping* quality issue, not necessarily fraud.

    Returns the flagged DataFrame (all booths; True flags on anomalous rows).
    Writes only flagged rows to *out_csv*.
    """
    df = pd.read_csv(party_shares_csv)
    df[ac_no_col] = pd.to_numeric(df[ac_no_col], errors="coerce").astype("Int64")
    df["total_votes"] = pd.to_numeric(df["total_votes"], errors="coerce")
    for col in ["BJP", "TMC", "tmc_share", "bjp_share", "other_share"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # AC-level booth counts for per-booth average
    ac_booth_counts = df.groupby(ac_no_col)[station_col].nunique().rename("ac_booths")
    df = df.join(ac_booth_counts, on=ac_no_col)
    df["ac_electors"] = df[ac_no_col].map(_NB_AC_ELECTORS)

    # -- Phantom booth: row votes exceed 5 % of entire AC electorate ----------
    df["flag_phantom_booth"] = (
        df["total_votes"] > df["ac_electors"] * 0.05
    ).fillna(False)

    # -- High votes: single-booth total > 2 000 --------------------------------
    df["flag_high_votes"] = (df["total_votes"] > 2000).fillna(False)

    # -- Low votes: > 0 but < 10 -----------------------------------------------
    df["flag_low_votes"] = (
        (df["total_votes"] > 0) & (df["total_votes"] < 10)
    ).fillna(False)

    # -- Party monopoly --------------------------------------------------------
    if "tmc_share" in df.columns and "bjp_share" in df.columns:
        df["flag_tmc_monopoly"] = (
            (df["tmc_share"] >= 0.99) & (df["total_votes"] > 100)
        ).fillna(False)
        df["flag_bjp_monopoly"] = (
            (df["bjp_share"] >= 0.99) & (df["total_votes"] > 100)
        ).fillna(False)
        df["flag_single_party_monopoly"] = df["flag_tmc_monopoly"] | df["flag_bjp_monopoly"]
    else:
        df["flag_tmc_monopoly"] = False
        df["flag_bjp_monopoly"] = False
        df["flag_single_party_monopoly"] = False

    # -- Zero named-party presence ---------------------------------------------
    if "BJP" in df.columns and "TMC" in df.columns:
        df["flag_zero_named_parties"] = (
            (df["BJP"].fillna(0) == 0)
            & (df["TMC"].fillna(0) == 0)
            & (df["total_votes"] >= 200)
        )
    else:
        df["flag_zero_named_parties"] = False

    flag_cols = [
        "flag_phantom_booth",
        "flag_high_votes",
        "flag_low_votes",
        "flag_single_party_monopoly",
        "flag_tmc_monopoly",
        "flag_bjp_monopoly",
        "flag_zero_named_parties",
    ]
    flagged = df[df[flag_cols].any(axis=1)].copy()

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    flagged.to_csv(out_csv, index=False)
    return df

