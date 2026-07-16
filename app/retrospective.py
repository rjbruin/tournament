"""
Retrospective analysis: how the tournament played out vs. pre-tournament
expectations.

Computed once when the final result is recorded, saved to
``data/retrospective.json``, and served from cache on all subsequent hits.

Data produced
-------------
- Pre-tournament odds for every team at every stage (group_advance, R16, QF,
  SF, Final, Winner) — from a clean engine run with no actuals.
- Per-match pre-match odds for every group-stage match (analytical from
  team Elos — no engine run needed since Elos are fixed at the draw).
- Per-match pre-match odds for every knockout match — one engine run per
  KO match, with actuals = {all results before that match}.
- Team "expected stage" (pre-tournament probability-weighted stage) vs
  actual stage reached, to surface over- and under-performers.
- Biggest upsets: all matches ranked by how unlikely the actual outcome was.
"""

from __future__ import annotations

import json
import os
import threading

from app.simulation.engine import GROUP_MATCH_PAIRS
from app.simulation.probability import match_outcome_probs

_RETRO_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "retrospective.json"
)

N_RETRO = 100_000

_retro_lock = threading.Lock()
_computing = False

# Display labels and numeric codes for tournament stages.
# 0=group out, 1=R32, 2=R16, 3=QF, 4=SF, 5=finalist, 6=winner
STAGE_LABELS = {0: "Group stage", 1: "R32", 2: "R16", 3: "QF",
                4: "SF", 5: "Final", 6: "Winner"}
ROUND_TO_STAGE = {"r32": 1, "r16": 2, "qf": 3, "sf": 4, "final": 6}


def load_retrospective() -> dict | None:
    path = os.path.realpath(_RETRO_PATH)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def save_retrospective(data: dict) -> None:
    path = os.path.realpath(_RETRO_PATH)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def is_tournament_complete(engine, actuals: dict) -> bool:
    final_no = engine.final_def["match"]
    return str(final_no) in actuals.get("knockout_results", {})


def compute_retrospective(engine, actuals: dict, n: int = N_RETRO) -> dict:
    """Full retrospective computation. Called in a background thread."""
    from datetime import datetime, timezone

    ko_results = actuals.get("knockout_results", {})
    ko_scores = actuals.get("knockout_scores", {})
    group_results = actuals.get("group_results", {})

    # ------------------------------------------------------------------
    # 1. Pre-tournament odds — one engine run with empty actuals
    # ------------------------------------------------------------------
    empty = {"group_results": {}, "knockout_results": {}}
    pre = engine.run(n, actuals=empty)
    pre_win = pre.get("winner_prob", {})
    pre_final = pre.get("finalist_prob", {})
    pre_sf = pre.get("semifinal_prob", {})
    pre_qf = pre.get("quarterfinal_prob", {})
    pre_r16 = pre.get("round_of_16_prob", {})
    pre_r32 = pre.get("group_advance_prob", {})

    # ------------------------------------------------------------------
    # 2. Group-stage match odds — analytical (Elos are static, no run)
    # ------------------------------------------------------------------
    group_match_odds: dict[str, list] = {}
    for grp in engine.groups:
        gname = grp["name"]
        teams = grp["teams"]
        odds_list = []
        for (i, j) in GROUP_MATCH_PAIRS:
            home, away = teams[i], teams[j]
            elo_h = float(engine.team_elos[engine.team_idx[home]])
            elo_a = float(engine.team_elos[engine.team_idx[away]])
            probs = match_outcome_probs(elo_h, elo_a, knockout=False, n=200_000)
            # Find actual result (API may have stored home/away reversed)
            pair = {home, away}
            actual = next(
                (r for r in group_results.get(gname, [])
                 if {r.get("home"), r.get("away")} == pair),
                None,
            )
            entry: dict = {"home": home, "away": away, **probs}
            if actual:
                hg, ag = actual["home_goals"], actual["away_goals"]
                a_home, a_away = actual.get("home"), actual.get("away")
                entry["actual_home"] = a_home
                entry["actual_away"] = a_away
                entry["actual_home_goals"] = hg
                entry["actual_away_goals"] = ag
                if a_home == home:
                    # stored in schedule orientation
                    if hg > ag:
                        entry["actual_outcome"] = "home_win"
                        entry["actual_result_prob"] = probs["home_win"]
                    elif hg == ag:
                        entry["actual_outcome"] = "draw"
                        entry["actual_result_prob"] = probs["draw"]
                    else:
                        entry["actual_outcome"] = "away_win"
                        entry["actual_result_prob"] = probs["away_win"]
                else:
                    # stored with teams reversed (API orientation)
                    if ag > hg:
                        entry["actual_outcome"] = "home_win"
                        entry["actual_result_prob"] = probs["home_win"]
                    elif hg == ag:
                        entry["actual_outcome"] = "draw"
                        entry["actual_result_prob"] = probs["draw"]
                    else:
                        entry["actual_outcome"] = "away_win"
                        entry["actual_result_prob"] = probs["away_win"]
            odds_list.append(entry)
        group_match_odds[gname] = odds_list

    # ------------------------------------------------------------------
    # 3. Knockout match odds — one engine run per KO match (progressive)
    # ------------------------------------------------------------------
    ko_schedule = engine.data.get("schedule", {}).get("knockout", {})
    ko_matches_sorted = sorted(
        [(mno, sched) for mno, sched in ko_schedule.items()
         if mno in ko_results],
        key=lambda x: (x[1].get("date", ""), int(x[0])),
    )

    ko_match_odds: dict[str, dict] = {}
    progressive_ko: dict[str, str] = {}  # built up as we go

    # Map bracket round name to each match number
    bracket = engine.data.get("bracket", {})
    match_to_round: dict[str, str] = {}
    for rnd, matches in bracket.items():
        if rnd in ("_note", "final"):
            continue
        for m in (matches if isinstance(matches, list) else []):
            match_to_round[str(m["match"])] = rnd
    match_to_round[str(engine.final_def["match"])] = "final"

    for mno_str, sched in ko_matches_sorted:
        run_actuals = {
            "group_results": group_results,
            "knockout_results": dict(progressive_ko),
        }
        results = engine.run(n, actuals=run_actuals)
        bm = results.get("bracket_matches", {})
        mno = int(mno_str)
        bme = bm.get(mno)
        if bme:
            home_side = bme.get("home") or {}
            away_side = bme.get("away") or {}
            entry: dict = {
                "home": home_side.get("team"),
                "away": away_side.get("team"),
                "round": match_to_round.get(mno_str, ""),
            }
            if bme.get("outcome"):
                entry.update(bme["outcome"])
            actual_winner = ko_results.get(mno_str)
            score = ko_scores.get(mno_str, {})
            entry["actual_winner"] = actual_winner
            entry["actual_home_goals"] = score.get("home_goals")
            entry["actual_away_goals"] = score.get("away_goals")
            entry["actual_home_penalties"] = score.get("home_penalties")
            entry["actual_away_penalties"] = score.get("away_penalties")
            if actual_winner and entry.get("home_win") is not None:
                if entry.get("home") == actual_winner:
                    entry["actual_result_prob"] = entry["home_win"]
                else:
                    entry["actual_result_prob"] = entry["away_win"]
            ko_match_odds[mno_str] = entry
        progressive_ko[mno_str] = ko_results[mno_str]

    # ------------------------------------------------------------------
    # 4. Actual stages reached per team
    # ------------------------------------------------------------------
    team_actual_stage: dict[str, int] = {}
    final_no_str = str(engine.final_def["match"])

    for mno_str, winner in ko_results.items():
        rnd = match_to_round.get(mno_str)
        if not rnd:
            continue
        stage = ROUND_TO_STAGE.get(rnd, 0)
        sc = ko_scores.get(mno_str, {})
        kmo = ko_match_odds.get(mno_str, {})
        home = sc.get("home") or kmo.get("home")
        away = sc.get("away") or kmo.get("away")
        if home:
            team_actual_stage[home] = max(team_actual_stage.get(home, 0), stage)
        if away:
            team_actual_stage[away] = max(team_actual_stage.get(away, 0), stage)

    # The final winner gets stage 6
    final_winner = ko_results.get(final_no_str)
    if final_winner:
        team_actual_stage[final_winner] = 6

    # All teams not in any KO match are group-stage exits (stage 0)
    for team in engine.team_names:
        team_actual_stage.setdefault(team, 0)

    # ------------------------------------------------------------------
    # 5. Expected stage per team (pre-tournament probability-weighted)
    # ------------------------------------------------------------------
    team_expected_stage: dict[str, float] = {}
    for team in engine.team_names:
        p_r32 = pre_r32.get(team, 0.0)
        p_r16 = pre_r16.get(team, 0.0)
        p_qf = pre_qf.get(team, 0.0)
        p_sf = pre_sf.get(team, 0.0)
        p_fp = pre_final.get(team, 0.0)
        p_win = pre_win.get(team, 0.0)
        # Marginal probabilities per stage
        p0 = 1.0 - p_r32
        p1 = max(0.0, p_r32 - p_r16)
        p2 = max(0.0, p_r16 - p_qf)
        p3 = max(0.0, p_qf - p_sf)
        p4 = max(0.0, p_sf - p_fp)
        p5 = max(0.0, p_fp - p_win)
        p6 = p_win
        team_expected_stage[team] = round(
            0*p0 + 1*p1 + 2*p2 + 3*p3 + 4*p4 + 5*p5 + 6*p6, 3
        )

    # ------------------------------------------------------------------
    # 6. Biggest upsets
    # ------------------------------------------------------------------
    all_matches: list[dict] = []
    for gname, odds_list in group_match_odds.items():
        for m in odds_list:
            if "actual_result_prob" not in m:
                continue
            all_matches.append({
                "type": "group",
                "group": gname,
                "home": m["home"],
                "away": m["away"],
                "actual_home": m.get("actual_home"),
                "actual_away": m.get("actual_away"),
                "actual_home_goals": m.get("actual_home_goals"),
                "actual_away_goals": m.get("actual_away_goals"),
                "actual_outcome": m.get("actual_outcome"),
                "actual_result_prob": m["actual_result_prob"],
                "home_win": m.get("home_win"),
                "draw": m.get("draw"),
                "away_win": m.get("away_win"),
            })
    for mno_str, m in ko_match_odds.items():
        if "actual_result_prob" not in m:
            continue
        all_matches.append({
            "type": "knockout",
            "match_no": mno_str,
            "round": m.get("round", ""),
            "home": m.get("home"),
            "away": m.get("away"),
            "actual_winner": m.get("actual_winner"),
            "actual_home_goals": m.get("actual_home_goals"),
            "actual_away_goals": m.get("actual_away_goals"),
            "actual_home_penalties": m.get("actual_home_penalties"),
            "actual_away_penalties": m.get("actual_away_penalties"),
            "actual_result_prob": m["actual_result_prob"],
            "home_win": m.get("home_win"),
            "away_win": m.get("away_win"),
        })
    all_matches.sort(key=lambda x: x["actual_result_prob"])
    biggest_upsets = all_matches[:10]

    # ------------------------------------------------------------------
    # 7. Key participants
    # ------------------------------------------------------------------
    final_score = ko_scores.get(final_no_str, {})
    finalists = []
    if final_score.get("home"):
        finalists.append(final_score["home"])
    if final_score.get("away"):
        finalists.append(final_score["away"])

    semifinalists = set()
    quarterfinalists = set()
    for m in bracket.get("sf", []):
        sc = ko_scores.get(str(m["match"]), {})
        if sc.get("home"):
            semifinalists.add(sc["home"])
        if sc.get("away"):
            semifinalists.add(sc["away"])
    for m in bracket.get("qf", []):
        sc = ko_scores.get(str(m["match"]), {})
        if sc.get("home"):
            quarterfinalists.add(sc["home"])
        if sc.get("away"):
            quarterfinalists.add(sc["away"])

    # Pre-tournament odds for the exact final pairing
    final_pair_prob = None
    if len(finalists) == 2:
        a, b = finalists
        # Probability both reached the final simultaneously
        final_pair_prob = round(pre_final.get(a, 0) * pre_final.get(b, 0) * 2, 5)

    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "winner": final_winner,
        "finalists": finalists,
        "semifinalists": sorted(semifinalists),
        "quarterfinalists": sorted(quarterfinalists),
        "pre_tournament": {
            "winner_prob": pre_win,
            "finalist_prob": pre_final,
            "semifinal_prob": pre_sf,
            "quarterfinal_prob": pre_qf,
            "round_of_16_prob": pre_r16,
            "group_advance_prob": pre_r32,
        },
        "final_pair_prob": final_pair_prob,
        "ko_match_odds": ko_match_odds,
        "group_match_odds": group_match_odds,
        "team_actual_stage": team_actual_stage,
        "team_expected_stage": team_expected_stage,
        "biggest_upsets": biggest_upsets,
    }


def trigger_retrospective_if_complete(engine, actuals: dict) -> None:
    """If the tournament is complete and the retrospective hasn't been
    computed yet, start a background thread to do it."""
    global _computing
    if not is_tournament_complete(engine, actuals):
        return
    if load_retrospective() is not None:
        return
    with _retro_lock:
        if _computing:
            return
        _computing = True

    def _run():
        global _computing
        try:
            import traceback
            print("[retrospective] Starting computation …")
            data = compute_retrospective(engine, actuals)
            save_retrospective(data)
            print("[retrospective] Done.")
        except Exception:
            traceback.print_exc()
        finally:
            _computing = False

    t = threading.Thread(target=_run, daemon=True, name="retrospective")
    t.start()
