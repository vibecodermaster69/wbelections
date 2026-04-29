from __future__ import annotations

from pathlib import Path
import shutil

import pandas as pd

from wb_election_pipeline.results_prefill import (
    fetch_eci_candidate_results,
    prefill_candidate_party_map,
    resolve_candidate_party_map,
)


def workspace_tmp(name: str) -> Path:
    path = Path(".tmp") / "tests" / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def test_prefill_candidate_party_map_matches_confident_names() -> None:
    tmp = workspace_tmp("prefill")
    scaffold = tmp / "scaffold.csv"
    results = tmp / "results.csv"
    out = tmp / "out.csv"
    pd.DataFrame(
        [
            {
                "ac_no": 1,
                "candidate": "Paresh Chandra Adhikary",
                "party": "",
                "is_placeholder_candidate": False,
                "is_non_candidate_header": False,
                "needs_review": True,
            },
            {
                "ac_no": 1,
                "candidate": "ADHIKARY",
                "party": "",
                "is_placeholder_candidate": False,
                "is_non_candidate_header": False,
                "needs_review": True,
            },
            {
                "ac_no": 1,
                "candidate": "candidate_col_1",
                "party": "",
                "is_placeholder_candidate": True,
                "is_non_candidate_header": False,
                "needs_review": True,
            },
        ]
    ).to_csv(scaffold, index=False)
    pd.DataFrame(
        [
            {
                "ac_no": 1,
                "winner_candidate": "Paresh Chandra Adhikary",
                "winner_party": "AITC",
                "runner_candidate": "Dadhiram Ray",
                "runner_party": "BJP",
            }
        ]
    ).to_csv(results, index=False)

    mapped = prefill_candidate_party_map(scaffold, results, out)
    assert mapped.loc[0, "party"] == "TMC"
    assert mapped.loc[1, "party"] == ""
    assert mapped.loc[2, "party"] == ""


def test_prefill_maps_non_model_parties_to_other() -> None:
    tmp = workspace_tmp("prefill_other")
    scaffold = tmp / "scaffold.csv"
    results = tmp / "results.csv"
    out = tmp / "out.csv"
    pd.DataFrame(
        [
            {
                "ac_no": 1,
                "candidate": "Some Regional",
                "party": "",
                "is_placeholder_candidate": False,
                "is_non_candidate_header": False,
                "needs_review": True,
            }
        ]
    ).to_csv(scaffold, index=False)
    pd.DataFrame(
        [
            {
                "ac_no": 1,
                "winner_candidate": "Some Regional",
                "winner_party": "GJM (TAMANG)",
                "runner_candidate": "Other Person",
                "runner_party": "BJP",
            }
        ]
    ).to_csv(results, index=False)
    mapped = prefill_candidate_party_map(scaffold, results, out, min_score=0.9)
    assert mapped.loc[0, "party"] == "OTHER"


def test_prefill_candidate_party_map_uses_eci_candidate_rows() -> None:
    tmp = workspace_tmp("prefill_eci")
    scaffold = tmp / "scaffold.csv"
    results = tmp / "eci_results.csv"
    out = tmp / "out.csv"
    pd.DataFrame(
        [
            {
                "ac_no": 1,
                "candidate": "Paresh Chandra Adhikary",
                "party": "",
                "is_placeholder_candidate": False,
                "is_non_candidate_header": False,
                "needs_review": True,
            },
            {
                "ac_no": 1,
                "candidate": "Dadhiram Ray",
                "party": "",
                "is_placeholder_candidate": False,
                "is_non_candidate_header": False,
                "needs_review": True,
            },
        ]
    ).to_csv(scaffold, index=False)
    pd.DataFrame(
        [
            {"ac_no": 1, "candidate": "PARESH CHANDRA ADHIKARY", "party": "All India Trinamool Congress"},
            {"ac_no": 1, "candidate": "DADHIRAM RAY", "party": "Bharatiya Janata Party"},
        ]
    ).to_csv(results, index=False)

    mapped = prefill_candidate_party_map(scaffold, results, out, min_score=0.9)
    assert mapped["party"].tolist() == ["TMC", "BJP"]
    assert mapped["prefill_source"].str.startswith("eci_candidate:").all()


def test_fetch_eci_candidate_results_normalizes_official_csv() -> None:
    tmp = workspace_tmp("eci_import")
    scope = tmp / "scope.csv"
    source = tmp / "official_eci.csv"
    out = tmp / "normalized.csv"
    pd.DataFrame([{"ac_no": 1, "ac_name": "Mekliganj"}]).to_csv(scope, index=False)
    pd.DataFrame(
        [
            {
                "Constituency": "Mekliganj",
                "Candidate": "Paresh Chandra Adhikary",
                "Party": "All India Trinamool Congress",
                "Total Votes": 106506,
            },
            {
                "Constituency": "Mekliganj",
                "Candidate": "Dadhiram Ray",
                "Party": "Bharatiya Janata Party",
                "Total Votes": 100888,
            },
        ]
    ).to_csv(source, index=False)

    normalized = fetch_eci_candidate_results(out, scope_csv=scope, input_csv=source)
    assert normalized[["ac_no", "candidate", "party"]].to_dict("records") == [
        {"ac_no": 1, "candidate": "Paresh Chandra Adhikary", "party": "TMC"},
        {"ac_no": 1, "candidate": "Dadhiram Ray", "party": "BJP"},
    ]


def test_fetch_eci_candidate_results_filters_to_scope_ac_numbers() -> None:
    tmp = workspace_tmp("eci_scope_filter")
    scope = tmp / "scope.csv"
    source = tmp / "official_eci.csv"
    out = tmp / "normalized.csv"
    pd.DataFrame([{"ac_no": 1, "district": "Cooch Behar"}]).to_csv(scope, index=False)
    pd.DataFrame(
        [
            {"ac_no": 1, "candidate": "Candidate One", "party": "AITC"},
            {"ac_no": 55, "candidate": "Candidate Outside Scope", "party": "BJP"},
        ]
    ).to_csv(source, index=False)

    normalized = fetch_eci_candidate_results(out, scope_csv=scope, input_csv=source)
    assert normalized["ac_no"].tolist() == [1]


def test_fetch_eci_candidate_results_normalizes_official_xlsx_header_offset() -> None:
    tmp = workspace_tmp("eci_import_xlsx")
    source = tmp / "official_eci.xlsx"
    out = tmp / "normalized.csv"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame(
            [
                ["10 - Detailed Results", None, None, None, None],
                [None, None, None, None, None],
                ["AC NO.", "AC NAME", "CANDIDATE NAME", "PARTY", "TOTAL"],
                [1, "Mekliganj", "1 ADHIKARY PARESH CHANDRA", "AITC", 99338],
                [1, "Mekliganj", "2 DADHIRAM RAY", "BJP", 84653],
            ]
        ).to_excel(writer, index=False, header=False)

    normalized = fetch_eci_candidate_results(out, input_csv=source)
    assert normalized[["ac_no", "ac_name", "candidate", "party", "total_votes"]].to_dict("records") == [
        {
            "ac_no": 1,
            "ac_name": "Mekliganj",
            "candidate": "ADHIKARY PARESH CHANDRA",
            "party": "TMC",
            "total_votes": 99338,
        },
        {
            "ac_no": 1,
            "ac_name": "Mekliganj",
            "candidate": "DADHIRAM RAY",
            "party": "BJP",
            "total_votes": 84653,
        },
    ]


def test_resolve_candidate_party_map_uses_guarded_fragment_matches() -> None:
    tmp = workspace_tmp("resolve_fragments")
    party_map = tmp / "party_map.csv"
    results = tmp / "eci.csv"
    overrides = tmp / "overrides.csv"
    out = tmp / "out.csv"
    unresolved = tmp / "unresolved.csv"
    pd.DataFrame(
        [
            {
                "ac_no": 7,
                "candidate": "NISITH",
                "party": "",
                "is_placeholder_candidate": False,
                "is_non_candidate_header": False,
                "candidate_votes_total": 100,
                "booth_count": 10,
                "needs_review": True,
            },
            {
                "ac_no": 7,
                "candidate": "PRADIP ROY, BJP",
                "party": "",
                "is_placeholder_candidate": False,
                "is_non_candidate_header": False,
                "candidate_votes_total": 50,
                "booth_count": 5,
                "needs_review": True,
            },
            {
                "ac_no": 7,
                "candidate": "RAY",
                "party": "",
                "is_placeholder_candidate": False,
                "is_non_candidate_header": False,
                "candidate_votes_total": 25,
                "booth_count": 2,
                "needs_review": True,
            },
            {
                "ac_no": 7,
                "candidate": "DU",
                "party": "",
                "is_placeholder_candidate": False,
                "is_non_candidate_header": False,
                "candidate_votes_total": 10,
                "booth_count": 1,
                "needs_review": True,
            },
            {
                "ac_no": 7,
                "candidate": "SWADHIN KUMAR MANDAL",
                "party": "",
                "is_placeholder_candidate": False,
                "is_non_candidate_header": False,
                "candidate_votes_total": 9,
                "booth_count": 1,
                "needs_review": True,
            },
        ]
    ).to_csv(party_map, index=False)
    pd.DataFrame(
        [
            {"ac_no": 7, "candidate": "NISITH PRAMANIK", "party": "BJP"},
            {"ac_no": 7, "candidate": "UDAYAN GUHA", "party": "AITC"},
            {"ac_no": 7, "candidate": "PRADIP ROY", "party": "OTHER"},
            {"ac_no": 7, "candidate": "KUMAR RAY", "party": "INC"},
            {"ac_no": 7, "candidate": "DIPAK KUMAR ROY", "party": "BJP"},
            {"ac_no": 7, "candidate": "SWADHIN KUMAR SARKAR", "party": "BJP"},
        ]
    ).to_csv(results, index=False)
    pd.DataFrame([{"ac_no": 7, "candidate": "DU", "party": "BJP", "source": "manual_test"}]).to_csv(
        overrides,
        index=False,
    )

    mapped = resolve_candidate_party_map(party_map, results, out, unresolved_out_csv=unresolved, overrides_csv=overrides)
    assert mapped.loc[0, "party"] == "BJP"
    assert mapped.loc[1, "party"] == "BJP"
    assert mapped.loc[2, "party"] == ""
    assert mapped.loc[3, "party"] == "BJP"
    assert mapped.loc[4, "party"] == "BJP"
    assert unresolved.exists()
