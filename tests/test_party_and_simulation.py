from __future__ import annotations

from pathlib import Path
import shutil

import pandas as pd

from wb_election_pipeline.party import aggregate_party_shares, normalize_party
from wb_election_pipeline.simulate import run_monte_carlo


def test_normalize_party() -> None:
    assert normalize_party("AITC") == "TMC"
    assert normalize_party("Bharatiya Janata Party") == "BJP"
    assert normalize_party("") == "OTHER"


def workspace_tmp(name: str) -> Path:
    path = Path(".tmp") / "tests" / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def test_aggregate_party_shares() -> None:
    tmp_path = workspace_tmp("aggregate")
    votes = tmp_path / "votes.csv"
    party_map = tmp_path / "party_map.csv"
    out = tmp_path / "shares.csv"

    pd.DataFrame(
        [
            {"ac_no": 1, "ac_name": "A", "polling_station": "1", "candidate": "Alpha", "votes": 60},
            {"ac_no": 1, "ac_name": "A", "polling_station": "1", "candidate": "Beta", "votes": 40},
            {"ac_no": 1, "ac_name": "A", "polling_station": "2", "candidate": "Alpha", "votes": 45},
            {"ac_no": 1, "ac_name": "A", "polling_station": "2", "candidate": "Beta", "votes": 55},
        ]
    ).to_csv(votes, index=False)
    pd.DataFrame(
        [
            {"ac_no": 1, "candidate": "Alpha", "party": "BJP"},
            {"ac_no": 1, "candidate": "Beta", "party": "AITC"},
        ]
    ).to_csv(party_map, index=False)

    result = aggregate_party_shares(votes, party_map, out)
    assert len(result) == 2
    assert result["BJP"].sum() == 105
    assert result["TMC"].sum() == 95
    assert out.exists()


def test_run_monte_carlo() -> None:
    tmp_path = workspace_tmp("simulate")
    booth_shares = tmp_path / "shares.csv"
    out = tmp_path / "sim.csv"
    pd.DataFrame(
        [
            {
                "ac_no": 1,
                "ac_name": "A",
                "polling_station": "1",
                "total_votes": 100,
                "bjp_share": 0.6,
                "tmc_share": 0.4,
            },
            {
                "ac_no": 1,
                "ac_name": "A",
                "polling_station": "2",
                "total_votes": 100,
                "bjp_share": 0.55,
                "tmc_share": 0.45,
            },
        ]
    ).to_csv(booth_shares, index=False)
    result = run_monte_carlo(booth_shares, out, iterations=200, noise_sd=0.0, ac_noise_sd=0.0)
    assert result.loc[0, "bjp_win_probability"] == 1.0
    assert out.exists()
