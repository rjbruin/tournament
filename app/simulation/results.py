"""
Canonical results dict: the sport/format-agnostic view of a TournamentRun.

Stage 1-3 templates keep reading the legacy WC-shaped dict via
app.simulation.compat_wc — this module is the forward-looking contract that
a future generic UI (or a new tournament with no legacy shim) would read
directly. Not yet consumed by any template.
"""

from __future__ import annotations

from dataclasses import asdict


def to_results(run) -> dict:
    reach_prob = run.ladder.reach_prob(run.reached, run.spec.entry_names)
    entries = [
        {"name": name, "elo": float(run.spec.entry_elos[i])}
        for i, name in enumerate(run.spec.entry_names)
    ]
    matches = []
    phases = {}
    for phase_id, result in run.phase_results.items():
        matches.extend(asdict(mr) for mr in result.matches)
        phases[phase_id] = {k: v for k, v in result.extra.items()}

    return {
        "meta": {
            "n_simulations": run.n,
            "elapsed_seconds": round(run.elapsed_seconds, 3),
            "stage_ids": run.spec.stage_ids,
        },
        "entries": entries,
        "stages": run.spec.stage_ids,
        "reach_prob": reach_prob,
        "matches": matches,
        "phases": phases,
    }
