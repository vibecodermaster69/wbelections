from __future__ import annotations

from pathlib import Path
import hashlib

import pandas as pd


REQUIRED_ROLL_COLUMNS = {
    "year",
    "ac_no",
    "part_no",
    "serial_no",
    "name",
    "relative_name",
    "gender",
    "age",
}


def normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).upper().replace(".", " ").split())


def voter_match_key(row: pd.Series) -> str:
    epic = normalize_text(row.get("epic_optional"))
    if epic:
        return f"EPIC:{hashlib.sha256(epic.encode('utf-8')).hexdigest()}"
    raw = "|".join(
        [
            normalize_text(row.get("name")),
            normalize_text(row.get("relative_name")),
            normalize_text(row.get("gender")),
            str(row.get("age", "")).strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_roll(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = REQUIRED_ROLL_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Roll CSV missing required columns: {sorted(missing)}")
    df = df.copy()
    df["ac_no"] = pd.to_numeric(df["ac_no"], errors="coerce").astype("Int64")
    df["part_no"] = df["part_no"].astype(str).str.strip()
    df["match_key"] = df.apply(voter_match_key, axis=1)
    return df


def compare_rolls(
    old_roll_csv: Path,
    new_roll_csv: Path,
    booth_out_csv: Path,
    ac_out_csv: Path,
    scope_csv: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    old = load_roll(old_roll_csv)
    new = load_roll(new_roll_csv)
    if scope_csv is not None:
        scope = pd.read_csv(scope_csv)
        scope["ac_no"] = pd.to_numeric(scope["ac_no"], errors="coerce").astype("Int64")
        old = old.merge(scope, on="ac_no", how="inner")
        new = new.merge(scope, on="ac_no", how="inner")

    old_keys = old[["ac_no", "part_no", "match_key"]].drop_duplicates()
    new_keys = new[["ac_no", "part_no", "match_key"]].drop_duplicates()

    old_by_booth = old_keys.groupby(["ac_no", "part_no"]).size().rename("old_roll_voters")
    new_by_booth = new_keys.groupby(["ac_no", "part_no"]).size().rename("new_roll_voters")
    retained = (
        old_keys.merge(new_keys, on=["ac_no", "part_no", "match_key"], how="inner")
        .groupby(["ac_no", "part_no"])
        .size()
        .rename("retained_voters")
    )
    deleted = (
        old_keys.merge(new_keys, on=["ac_no", "part_no", "match_key"], how="left", indicator=True)
        .query("_merge == 'left_only'")
        .groupby(["ac_no", "part_no"])
        .size()
        .rename("deleted_or_unmatched_voters")
    )
    added = (
        new_keys.merge(old_keys, on=["ac_no", "part_no", "match_key"], how="left", indicator=True)
        .query("_merge == 'left_only'")
        .groupby(["ac_no", "part_no"])
        .size()
        .rename("added_or_unmatched_voters")
    )

    booth = pd.concat([old_by_booth, new_by_booth, retained, deleted, added], axis=1).fillna(0).reset_index()
    numeric_cols = [
        "old_roll_voters",
        "new_roll_voters",
        "retained_voters",
        "deleted_or_unmatched_voters",
        "added_or_unmatched_voters",
    ]
    booth[numeric_cols] = booth[numeric_cols].astype(int)
    booth["retention_rate"] = (
        booth["retained_voters"] / booth["old_roll_voters"].where(booth["old_roll_voters"] > 0)
    ).round(4)
    booth["deletion_rate"] = (
        booth["deleted_or_unmatched_voters"] / booth["old_roll_voters"].where(booth["old_roll_voters"] > 0)
    ).round(4)
    booth["net_roll_change"] = booth["new_roll_voters"] - booth["old_roll_voters"]

    ac = (
        booth.groupby("ac_no")
        .agg(
            booths=("part_no", "nunique"),
            old_roll_voters=("old_roll_voters", "sum"),
            new_roll_voters=("new_roll_voters", "sum"),
            retained_voters=("retained_voters", "sum"),
            deleted_or_unmatched_voters=("deleted_or_unmatched_voters", "sum"),
            added_or_unmatched_voters=("added_or_unmatched_voters", "sum"),
            net_roll_change=("net_roll_change", "sum"),
        )
        .reset_index()
    )
    ac["retention_rate"] = (
        ac["retained_voters"] / ac["old_roll_voters"].where(ac["old_roll_voters"] > 0)
    ).round(4)
    ac["deletion_rate"] = (
        ac["deleted_or_unmatched_voters"] / ac["old_roll_voters"].where(ac["old_roll_voters"] > 0)
    ).round(4)

    booth_out_csv.parent.mkdir(parents=True, exist_ok=True)
    booth.to_csv(booth_out_csv, index=False)
    ac.to_csv(ac_out_csv, index=False)
    return booth, ac
