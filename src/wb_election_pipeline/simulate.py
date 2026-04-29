from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def run_monte_carlo(
    booth_shares_csv: Path,
    out_csv: Path,
    iterations: int = 10000,
    turnout_change: float = 0.0,
    sir_deletion_factor: float = 0.0,
    tmc_to_bjp_swing: float = 0.0,
    noise_sd: float = 0.015,
    ac_noise_sd: float = 0.04,
    seed: int = 42,
) -> pd.DataFrame:
    """Run Monte Carlo simulation of AC-level election outcomes.

    Noise model: each iteration draws an AC-level correlated shock (``ac_noise_sd``)
    that shifts all booths in the same AC equally, plus an independent booth-level
    idiosyncratic shock (``noise_sd``).  This prevents the AC-level noise from
    averaging away and keeps competitive seats genuinely uncertain.
    """
    booths = pd.read_csv(booth_shares_csv)
    required = {"ac_no", "ac_name", "polling_station", "total_votes", "bjp_share", "tmc_share"}
    missing = required - set(booths.columns)
    if missing:
        raise ValueError(f"Booth share CSV missing columns: {sorted(missing)}")

    rng = np.random.default_rng(seed)
    records: list[dict[str, object]] = []
    base_votes = booths["total_votes"].to_numpy(dtype=float)
    adjusted_total = np.maximum(base_votes * (1.0 - sir_deletion_factor) * (1.0 + turnout_change), 0.0)
    base_bjp = booths["bjp_share"].fillna(0).to_numpy(dtype=float)
    base_tmc = booths["tmc_share"].fillna(0).to_numpy(dtype=float)
    two_party_total = np.maximum(base_bjp + base_tmc, 1e-9)
    base_bjp_two_party = base_bjp / two_party_total

    ac_keys = booths[["ac_no", "ac_name"]].drop_duplicates().sort_values("ac_no")
    ac_nos = ac_keys["ac_no"].to_numpy(dtype=int)
    ac_index = booths["ac_no"].to_numpy(dtype=int)

    # Map each booth to its AC index for vectorised AC-level noise broadcast
    ac_no_to_idx = {ac_no: i for i, ac_no in enumerate(ac_nos)}
    booth_ac_idx = np.array([ac_no_to_idx[a] for a in ac_index], dtype=int)

    bjp_wins = {int(ac_no): 0 for ac_no in ac_nos}
    tmc_wins = {int(ac_no): 0 for ac_no in ac_nos}
    bjp_vote_sum = {int(ac_no): 0.0 for ac_no in ac_nos}
    tmc_vote_sum = {int(ac_no): 0.0 for ac_no in ac_nos}

    n_acs = len(ac_nos)
    for _ in range(iterations):
        # AC-level correlated shock: same shift applied to every booth in an AC
        ac_shock = rng.normal(0.0, ac_noise_sd, size=n_acs)
        # Booth-level idiosyncratic noise
        booth_noise = rng.normal(0.0, noise_sd, size=len(booths))
        total_noise = ac_shock[booth_ac_idx] + booth_noise

        bjp_two_party = np.clip(base_bjp_two_party + tmc_to_bjp_swing + total_noise, 0.0, 1.0)
        bjp_votes = adjusted_total * bjp_two_party
        tmc_votes = adjusted_total * (1.0 - bjp_two_party)

        # Vectorised AC aggregation
        bjp_ac = np.bincount(booth_ac_idx, weights=bjp_votes, minlength=n_acs)
        tmc_ac = np.bincount(booth_ac_idx, weights=tmc_votes, minlength=n_acs)

        for i, ac_no in enumerate(ac_nos):
            bjp_total = float(bjp_ac[i])
            tmc_total = float(tmc_ac[i])
            bjp_vote_sum[ac_no] += bjp_total
            tmc_vote_sum[ac_no] += tmc_total
            if bjp_total > tmc_total:
                bjp_wins[ac_no] += 1
            else:
                tmc_wins[ac_no] += 1

    for i, ac_no in enumerate(ac_nos):
        ac_name = ac_keys.iloc[i]["ac_name"]
        records.append(
            {
                "ac_no": int(ac_no),
                "ac_name": ac_name,
                "iterations": iterations,
                "mean_bjp_votes": bjp_vote_sum[ac_no] / iterations,
                "mean_tmc_votes": tmc_vote_sum[ac_no] / iterations,
                "bjp_win_probability": bjp_wins[ac_no] / iterations,
                "tmc_win_probability": tmc_wins[ac_no] / iterations,
                "expected_margin": (bjp_vote_sum[ac_no] - tmc_vote_sum[ac_no]) / iterations,
                "turnout_change": turnout_change,
                "sir_deletion_factor": sir_deletion_factor,
                "tmc_to_bjp_swing": tmc_to_bjp_swing,
                "noise_sd": noise_sd,
                "ac_noise_sd": ac_noise_sd,
            }
        )

    result = pd.DataFrame(records)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_csv, index=False)
    return result

