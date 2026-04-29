from __future__ import annotations

from pathlib import Path
import shutil

import pandas as pd

from wb_election_pipeline.north_bengal import build_booth_features, build_candidate_party_scaffold, build_scoped_candidate_votes
from wb_election_pipeline.voter_roll_extract import parse_roll_count_markdown_file, parse_roll_markdown_file
from wb_election_pipeline.voter_roll_match import compare_rolls


def workspace_tmp(name: str) -> Path:
    path = Path(".tmp") / "tests" / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def test_compare_rolls() -> None:
    tmp = workspace_tmp("rolls")
    old_roll = tmp / "old.csv"
    new_roll = tmp / "new.csv"
    booth_out = tmp / "booth.csv"
    ac_out = tmp / "ac.csv"
    base_cols = ["year", "ac_no", "part_no", "serial_no", "name", "relative_name", "gender", "age"]
    pd.DataFrame(
        [
            [2021, 1, "1", 1, "A One", "R One", "F", 40],
            [2021, 1, "1", 2, "B Two", "R Two", "M", 50],
        ],
        columns=base_cols,
    ).to_csv(old_roll, index=False)
    pd.DataFrame(
        [
            [2026, 1, "1", 1, "A One", "R One", "F", 40],
            [2026, 1, "1", 3, "C Three", "R Three", "F", 22],
        ],
        columns=base_cols,
    ).to_csv(new_roll, index=False)

    booth, ac = compare_rolls(old_roll, new_roll, booth_out, ac_out)
    assert booth.loc[0, "old_roll_voters"] == 2
    assert booth.loc[0, "new_roll_voters"] == 2
    assert booth.loc[0, "retained_voters"] == 1
    assert booth.loc[0, "deleted_or_unmatched_voters"] == 1
    assert booth.loc[0, "added_or_unmatched_voters"] == 1
    assert ac.loc[0, "deletion_rate"] == 0.5


def test_parse_bengali_gemini_roll_table() -> None:
    tmp = workspace_tmp("bengali_roll")
    markdown = tmp / "AC001PART001_page002.md"
    markdown.write_text(
        "\n".join(
            [
                "| ক্রমিক নং | বুথ নং | নাম | সম্পর্ক | সম্পর্কের নাম | লিঙ্গ | বয়স | পরিচয়পত্র নং |",
                "|---|---|---|---|---|---|---|---|",
                "| ১ | | অনঙ্গন অধিকারী | পিতা | গোবিন্দ অধিকারী | পূং | ৪২ | WB/03/001/000183 |",
                "| ২ | | ভারতী অধিকারী | স্বামী | নীরেন অধিকারী | স্ত্রী | ২৬ | HJK1504299 |",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_roll_markdown_file(markdown, year=2026)

    assert len(parsed) == 2
    assert parsed.loc[0, "ac_no"] == 1
    assert parsed.loc[0, "part_no"] == "1"
    assert parsed.loc[0, "serial_no"] == "1"
    assert parsed.loc[0, "age"] == "42"
    assert parsed.loc[1, "name"] == "ভারতী অধিকারী"
    assert parsed.loc[1, "relative_name"] == "নীরেন অধিকারী"


def test_parse_roll_counts_and_join_features() -> None:
    tmp = workspace_tmp("roll_counts")
    markdown = tmp / "AC001PART001.md"
    markdown.write_text(
        "\n".join(
            [
                "| serial_no | part_no | name | relation_type | relative_name | gender | age | epic_optional |",
                "|---|---|---|---|---|---|---|---|",
                "| 1 | | A One | father | R One | M | 40 | AAA001 |",
                "| 2 | | B Two | father | R Two | F | 35 | AAA002 |",
                "| 4 | | D Four | father | R Four | M | 30 | AAA004 |",
            ]
        ),
        encoding="utf-8",
    )

    counts = parse_roll_count_markdown_file(markdown, year=2026)
    assert counts.loc[0, "registered_voters"] == 4
    assert counts.loc[0, "parsed_rows"] == 3
    assert counts.loc[0, "serial_gaps"] == 1

    party = tmp / "party.csv"
    scope = tmp / "scope.csv"
    count_csv = tmp / "counts.csv"
    out = tmp / "features.csv"
    pd.DataFrame(
        [
            {
                "ac_no": 1,
                "ac_name": "A",
                "polling_station": "1",
                "BJP": 50,
                "TMC": 40,
                "OTHER": 10,
                "total_votes": 100,
                "bjp_share": 0.5,
                "tmc_share": 0.4,
                "other_share": 0.1,
            }
        ]
    ).to_csv(party, index=False)
    pd.DataFrame([{"ac_no": 1, "district": "Cooch Behar", "region_scope": "North Bengal"}]).to_csv(scope, index=False)
    counts.to_csv(count_csv, index=False)

    features = build_booth_features(party, count_csv, None, scope, out)
    assert features.loc[0, "registered_voters_2026"] == 4
    assert bool(features.loc[0, "model_ready_booth"])


def test_north_bengal_clean_and_party_scaffold() -> None:
    tmp = workspace_tmp("north_bengal")
    votes = tmp / "votes.csv"
    quality = tmp / "quality.csv"
    scope = tmp / "scope.csv"
    clean = tmp / "clean.csv"
    scaffold = tmp / "scaffold.csv"

    pd.DataFrame(
        [
            {
                "ac_no": 1,
                "ac_name": "A",
                "polling_station": "1",
                "candidate": "Alpha",
                "votes": 10,
                "total_valid_votes": 20,
            },
            {
                "ac_no": 1,
                "ac_name": "A",
                "polling_station": "1",
                "candidate": "candidate_col_2",
                "votes": 5,
                "total_valid_votes": 20,
            },
        ]
    ).to_csv(votes, index=False)
    pd.DataFrame(
        [
            {
                "ac_no": 1,
                "booths": 200,
                "total_valid_coverage_pct": 0.8,
                "placeholder_booth_pct": 0.1,
                "booths_low_candidate_count": 0,
                "booths_with_placeholders": 1,
            }
        ]
    ).to_csv(quality, index=False)
    pd.DataFrame([{"ac_no": 1, "district": "Cooch Behar", "region_scope": "North Bengal"}]).to_csv(
        scope,
        index=False,
    )

    clean_df = build_scoped_candidate_votes(votes, quality, scope, clean)
    assert len(clean_df) == 2
    assert clean_df["form20_model_ready"].sum() == 1

    scaffold_df = build_candidate_party_scaffold(clean, scaffold)
    assert set(scaffold_df["candidate"]) == {"Alpha", "candidate_col_2"}
    assert scaffold.exists()
