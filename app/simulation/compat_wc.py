"""
Legacy WC2026 results shim: builds the EXACT dict shape
``SimulationEngine.run()`` has always returned, from a generic
``TournamentRun``. Exists so Stages 1-3 require zero template/route changes
while the engine itself is fully generalized underneath — deleted once the
UI reads the canonical ``results.py`` contract directly (a later stage).

Validated for exact parity against the pre-refactor engine in
tests/golden/test_compat_wc.py (the plan's "T3 gate").

Two round-name spellings coexist in the legacy contract and must both be
reproduced exactly (a real inconsistency in the original code, not a typo
here): ``bracket_matches[...]["round"]`` uses the SINGULAR form
("Quarterfinal", "Semifinal" — engine.py:175-184's ``ROUND_NAMES``), while
``opponent_probs[team][round]`` uses the PLURAL form ("Quarterfinals",
"Semifinals" — engine.py:760-766's local ``rounds`` list, consumed by
templates like team.html which look up the plural).
"""

from __future__ import annotations

import numpy as np

ROUND_LABEL_SINGULAR = {
    "r32": "Round of 32", "r16": "Round of 16", "qf": "Quarterfinal",
    "sf": "Semifinal", "final": "Final",
}
ROUND_LABEL_PLURAL = [
    ("r32", "Round of 32"), ("r16", "Round of 16"), ("qf", "Quarterfinals"),
    ("sf", "Semifinals"), ("final", "Final"),
]


def _build_group_finish(run) -> dict:
    standings = run.phase_results["groups"].extra["standings"]
    reach_prob = run.ladder.reach_prob(run.reached, run.spec.entry_names)
    r32_prob = reach_prob["r32"]

    out = {}
    for letter in run.spec.group_letters:
        st = standings[letter]
        order = st["order"]              # (n, 4) original-position index at each rank
        positions0 = st["positions"][0]  # (4,) entry idx at each original position (static)
        out[letter] = {}
        for p in range(4):
            team_idx = int(positions0[p])
            team_name = run.spec.entry_names[team_idx]
            advance = r32_prob[team_name]
            out[letter][team_name] = {
                "first_prob": round(float(np.mean(order[:, 0] == p)), 4),
                "second_prob": round(float(np.mean(order[:, 1] == p)), 4),
                "third_prob": round(float(np.mean(order[:, 2] == p)), 4),
                "fourth_prob": round(float(np.mean(order[:, 3] == p)), 4),
                "advance_prob": advance,
                "eliminate_prob": round(1 - advance, 4),
            }
    return out


def _build_fixtures(run) -> dict:
    fixtures = {letter: [] for letter in run.spec.group_letters}
    for mr in run.phase_results["groups"].matches:
        letter = mr.extra["group"]
        match = {"home": mr.side_a["team"], "away": mr.side_b["team"]}
        if mr.actual is not None:
            match["home_goals"] = int(mr.actual["home_goals"])
            match["away_goals"] = int(mr.actual["away_goals"])
            match["played"] = True
        else:
            match["played"] = False
            match["odds"] = mr.outcome
        fixtures[letter].append(match)
    return fixtures


def _build_bracket_matches(run) -> dict:
    out = {}
    for mr in run.phase_results["ko"].matches:
        mno = mr.number
        out[mno] = {
            "match": mno,
            "round": ROUND_LABEL_SINGULAR.get(mr.round_id, ""),
            "home": {"determined": mr.side_a["determined"], "team": mr.side_a["team"],
                      "elo": mr.side_a["elo"], "candidates": mr.side_a["candidates"]},
            "away": {"determined": mr.side_b["determined"], "team": mr.side_b["team"],
                      "elo": mr.side_b["elo"], "candidates": mr.side_b["candidates"]},
            "outcome": mr.outcome,
            "actual_winner": mr.actual["winner"] if mr.actual else None,
        }
    return out


def _build_opponent_probs(run) -> dict:
    opponent_data = run.phase_results["ko"].extra["opponent_data"]
    entry_names = run.spec.entry_names
    out = {name: {} for name in entry_names}
    for round_id, label in ROUND_LABEL_PLURAL:
        od = opponent_data[round_id]
        opp_counts = od["opp_counts"]
        appearances = od["appearances"]
        for tidx, tname in enumerate(entry_names):
            total = appearances[tidx]
            if total == 0:
                continue
            probs = opp_counts[tidx] / total
            top_idx = np.argsort(-probs)[:5]
            opponents = [
                {"team": entry_names[i], "probability": round(float(probs[i]), 4)}
                for i in top_idx if probs[i] > 0
            ]
            if opponents:
                out[tname][label] = opponents
    return out


def _attach_schedule(results: dict, run) -> None:
    schedule = run.spec.raw_data["tournament_data"].get("schedule")
    if not schedule:
        return
    for letter in run.spec.group_letters:
        sched_matches = schedule.get("groups", {}).get(letter, [])
        for match, sm in zip(results["fixtures"].get(letter, []), sched_matches):
            match["date"] = sm["date"]
            match["local_time"] = sm["local_time"]
            match["local_timezone"] = sm["local_timezone"]
            match["venue"] = sm["venue"]
            match["place"] = sm["place"]
            if "match" in sm:
                match["match"] = sm["match"]
    for mno_str, sm in schedule.get("knockout", {}).items():
        m = results["bracket_matches"].get(int(mno_str))
        if m is not None:
            m["date"] = sm["date"]
            m["local_time"] = sm["local_time"]
            m["local_timezone"] = sm["local_timezone"]
            m["venue"] = sm["venue"]
            m["place"] = sm["place"]


def to_legacy_results(run) -> dict:
    """Build the full legacy ``SimulationEngine.run()``-shaped dict from a
    ``TournamentRun``. WC2026-specific (relies on the "groups"/"ko" phase
    ids and the r32/r16/qf/sf/final/champion stage ladder)."""
    reach_prob = run.ladder.reach_prob(run.reached, run.spec.entry_names)

    results = {
        "group_advance_prob": reach_prob["r32"],
        "round_of_16_prob": reach_prob["r16"],
        "quarterfinal_prob": reach_prob["qf"],
        "semifinal_prob": reach_prob["sf"],
        "finalist_prob": reach_prob["final"],
        "winner_prob": reach_prob["champion"],
        "group_finish": _build_group_finish(run),
        "opponent_probs": _build_opponent_probs(run),
        "fixtures": _build_fixtures(run),
        "bracket_matches": _build_bracket_matches(run),
        "n_simulations": run.n,
        "elapsed_seconds": round(run.elapsed_seconds, 3),
    }
    _attach_schedule(results, run)
    return results
