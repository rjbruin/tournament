"""
Vectorized Monte Carlo simulation engine for the 2026 World Cup format:
48 teams, 12 groups of 4, top 2 per group + 8 best third-placed teams
advance to a 32-team knockout bracket (R32 -> R16 -> QF -> SF -> Final),
following the real FIFA bracket (matches 73-103) and the official
Annex C third-place placement table.

All N simulations run in parallel using NumPy array operations. Every
single fixture (group-stage and knockout) is simulated individually -
there are no shortcuts based on aggregate group/team Elo.

The engine can be conditioned on "actual" results entered as the real
tournament progresses (see app/data_store.py): played group matches use
the real scoreline for every simulation, and knockout matches with a
recorded winner are forced to that outcome.
"""

import contextlib
import json
import os

import numpy as np
import time

from app.simulation.probability import compute_lambdas_vec, penalty_win_prob, match_outcome_probs

# Group-stage match order: index pairs into a group's 4-team list.
GROUP_MATCH_PAIRS = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]

ROUND_NAMES = {}
for _m in range(73, 89):
    ROUND_NAMES[_m] = "Round of 32"
for _m in range(89, 97):
    ROUND_NAMES[_m] = "Round of 16"
for _m in range(97, 101):
    ROUND_NAMES[_m] = "Quarterfinal"
for _m in (101, 102):
    ROUND_NAMES[_m] = "Semifinal"
ROUND_NAMES[103] = "Final"


class SimulationEngine:
    def __init__(self, tournament_data: dict):
        self.data = tournament_data
        teams = tournament_data["teams"]
        self.team_names = [t["name"] for t in teams]
        self.team_elos = np.array([t["elo"] for t in teams], dtype=float)
        self.team_idx = {name: i for i, name in enumerate(self.team_names)}
        self.groups = tournament_data["groups"]
        self.n_groups = len(self.groups)
        self.group_letters = [g["name"] for g in self.groups]
        self.group_pos = {name: i for i, name in enumerate(self.group_letters)}

        # Pre-build group team index arrays (each shape (4,))
        self._group_indices = [
            np.array([self.team_idx[name] for name in g["teams"]], dtype=int)
            for g in self.groups
        ]
        # name -> position (0-3) within its group
        self._group_team_pos = [
            {name: pos for pos, name in enumerate(g["teams"])}
            for g in self.groups
        ]

        # Load Annex C lookup table for third-place placements
        annex_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "annex_c.json")
        with open(annex_path) as f:
            annex = json.load(f)
        self.annex_match_order = annex["match_order"]  # [74,77,79,80,81,82,85,87]
        # Build dense LUT array of size 4096: bitmask -> 8 group indices (or -1 if invalid)
        self._annex_lut = np.full((4096, 8), -1, dtype=int)
        for bitmask_str, group_idxs in annex["lut"].items():
            self._annex_lut[int(bitmask_str)] = group_idxs

        bracket = tournament_data["bracket"]
        self.r32_defs = bracket["r32"]
        self.r16_defs = bracket["r16"]
        self.qf_defs = bracket["qf"]
        self.sf_defs = bracket["sf"]
        self.final_def = bracket["final"]
        self.all_knockout_defs = (
            self.r32_defs + self.r16_defs + self.qf_defs + self.sf_defs + [self.final_def]
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, n: int = 10_000, actuals: dict | None = None, groups: dict | None = None) -> dict:
        with self._temporary_groups(groups):
            t0 = time.perf_counter()
            actuals = actuals or {"group_results": {}, "knockout_results": {}}

            fixed_group_results = self._resolve_fixed_group_results(actuals.get("group_results", {}))
            fixed_knockout_winners = self._resolve_fixed_knockout_winners(actuals.get("knockout_results", {}))

            # group_order[sim, g, pos] = team index at rank `pos` (0=1st..3=4th)
            # group_key[sim, g, pos]   = ranking key at that rank (for 3rd-place comparison)
            group_order, group_key = self._simulate_group_stage(n, fixed_group_results)

            results = self._simulate_knockout(n, group_order, group_key, fixed_knockout_winners)

            results["fixtures"] = self._build_group_fixtures(actuals.get("group_results", {}), actuals.get("live_matches"))
            results["bracket_matches"] = results.pop("_bracket_matches")
            for m in results["bracket_matches"].values():
                mn = m["match"]
                if str(mn) in actuals.get("knockout_results", {}):
                    m["actual_winner"] = actuals["knockout_results"][str(mn)]

            self._attach_schedule(results)

            elapsed = time.perf_counter() - t0
            results["n_simulations"] = n
            results["elapsed_seconds"] = round(elapsed, 3)
            return results

    @contextlib.contextmanager
    def _temporary_groups(self, groups_override: dict | None):
        """If ``groups_override`` (a ``{letter: [4 team names]}`` dict) is
        given, temporarily replace ``self.groups``, ``self._group_indices``
        and ``self._group_team_pos`` with versions reflecting that
        composition (in ``self.group_letters`` order), restoring the
        originals afterwards. A no-op if ``groups_override`` is falsy."""
        if not groups_override:
            yield
            return

        original_groups = self.groups
        original_indices = self._group_indices
        original_team_pos = self._group_team_pos

        new_groups = []
        new_indices = []
        new_team_pos = []
        for letter in self.group_letters:
            teams = groups_override[letter]
            new_groups.append({"name": letter, "teams": list(teams)})
            new_indices.append(np.array([self.team_idx[name] for name in teams], dtype=int))
            new_team_pos.append({name: pos for pos, name in enumerate(teams)})

        self.groups = new_groups
        self._group_indices = new_indices
        self._group_team_pos = new_team_pos
        try:
            yield
        finally:
            self.groups = original_groups
            self._group_indices = original_indices
            self._group_team_pos = original_team_pos

    # ------------------------------------------------------------------
    # Conditioning on actual results
    # ------------------------------------------------------------------

    def _resolve_fixed_group_results(self, group_results: dict) -> dict:
        """
        Returns {group_name: {(i, j): (goals_i, goals_j)}} where (i, j) is one
        of GROUP_MATCH_PAIRS (positions within the group's team list) and
        goals_i/goals_j are the recorded scoreline for that pairing.
        """
        fixed = {}
        for gname, played in group_results.items():
            if gname not in self.group_pos:
                continue
            pos = self._group_team_pos[self.group_pos[gname]]
            fixed_pairs = {}
            for entry in played:
                home, away = entry.get("home"), entry.get("away")
                if home not in pos or away not in pos:
                    continue
                hp, ap = pos[home], pos[away]
                hg, ag = int(entry["home_goals"]), int(entry["away_goals"])
                for (i, j) in GROUP_MATCH_PAIRS:
                    if {i, j} == {hp, ap}:
                        if i == hp:
                            fixed_pairs[(i, j)] = (hg, ag)
                        else:
                            fixed_pairs[(i, j)] = (ag, hg)
                        break
            if fixed_pairs:
                fixed[gname] = fixed_pairs
        return fixed

    def _resolve_fixed_knockout_winners(self, knockout_results: dict) -> dict:
        """Returns {match_no (int): team_idx} for matches with a recorded winner."""
        fixed = {}
        for match_no, team_name in knockout_results.items():
            if team_name in self.team_idx:
                fixed[int(match_no)] = self.team_idx[team_name]
        return fixed

    # ------------------------------------------------------------------
    # Group stage (4 teams, 6 matches)
    # ------------------------------------------------------------------

    def _simulate_group_stage(self, n: int, fixed_group_results: dict):
        group_order = np.empty((n, self.n_groups, 4), dtype=int)
        group_key = np.empty((n, self.n_groups, 4), dtype=np.int64)

        for gi, tidx in enumerate(self._group_indices):
            gname = self.group_letters[gi]
            fixed_pairs = fixed_group_results.get(gname, {})
            pts, gf, ga = self._simulate_group(n, tidx, fixed_pairs)
            gd = gf - ga
            key = pts.astype(np.int64) * 1_000_000 + gd.astype(np.int64) * 1_000 + gf.astype(np.int64)
            order = np.argsort(-key, axis=1, kind="stable")  # (n, 4) descending
            for pos in range(4):
                group_order[:, gi, pos] = tidx[order[:, pos]]
                group_key[:, gi, pos] = np.take_along_axis(key, order[:, pos:pos+1], axis=1)[:, 0]

        return group_order, group_key

    def _simulate_group(self, n: int, tidx: np.ndarray, fixed_pairs: dict):
        """tidx: (4,) team indices. Returns pts, gf, ga each (n, 4)."""
        pts = np.zeros((n, 4), dtype=int)
        gf = np.zeros((n, 4), dtype=int)
        ga = np.zeros((n, 4), dtype=int)

        for i, j in GROUP_MATCH_PAIRS:
            if (i, j) in fixed_pairs:
                gi_val, gj_val = fixed_pairs[(i, j)]
                goals_i = np.full(n, gi_val, dtype=int)
                goals_j = np.full(n, gj_val, dtype=int)
            else:
                la, lb = compute_lambdas_vec(self.team_elos[tidx[i]], self.team_elos[tidx[j]])
                goals_i = np.random.poisson(la, n)
                goals_j = np.random.poisson(lb, n)

            gf[:, i] += goals_i
            gf[:, j] += goals_j
            ga[:, i] += goals_j
            ga[:, j] += goals_i

            win_i = goals_i > goals_j
            win_j = goals_j > goals_i
            draw = goals_i == goals_j

            pts[:, i] += 3 * win_i + draw
            pts[:, j] += 3 * win_j + draw

        return pts, gf, ga

    def _simulate_group_capture(self, n: int, tidx: np.ndarray, fixed_pairs: dict):
        """Like :meth:`_simulate_group` but also returns the per-simulation
        scoreline of every match: ``scorelines[(i, j)] = (goals_i, goals_j)``,
        each an ``(n,)`` array."""
        pts = np.zeros((n, 4), dtype=int)
        gf = np.zeros((n, 4), dtype=int)
        ga = np.zeros((n, 4), dtype=int)
        scorelines = {}

        for i, j in GROUP_MATCH_PAIRS:
            if (i, j) in fixed_pairs:
                gi_val, gj_val = fixed_pairs[(i, j)]
                goals_i = np.full(n, gi_val, dtype=int)
                goals_j = np.full(n, gj_val, dtype=int)
            else:
                la, lb = compute_lambdas_vec(self.team_elos[tidx[i]], self.team_elos[tidx[j]])
                goals_i = np.random.poisson(la, n)
                goals_j = np.random.poisson(lb, n)

            gf[:, i] += goals_i
            gf[:, j] += goals_j
            ga[:, i] += goals_j
            ga[:, j] += goals_i

            win_i = goals_i > goals_j
            win_j = goals_j > goals_i
            draw = goals_i == goals_j
            pts[:, i] += 3 * win_i + draw
            pts[:, j] += 3 * win_j + draw

            scorelines[(i, j)] = (goals_i, goals_j)

        return pts, gf, ga, scorelines

    def simulate_group_outcomes(self, n: int, actuals: dict | None, group_name: str) -> dict:
        """Monte-Carlo a tournament conditioned on ``actuals`` and return, for
        ``group_name``, the raw per-simulation data needed to reason about
        qualification:

          - ``matches``: one dict per *unplayed* match of the group (in
            schedule order), with ``home``/``away`` team names and the (n,)
            arrays ``result`` (+1 home win, 0 draw, -1 away win) and ``gd``
            (home goals minus away goals);
          - ``outcomes``: ``{team_name: {"first", "second", "advanced"}}`` of
            (n,) boolean arrays — whether that team finishes 1st / 2nd / reaches
            the knockouts (top-2 or one of the 8 best third-placed teams).

        The third-place race is resolved against every other group (simulated
        too), so ``advanced`` correctly depends on results elsewhere.
        """
        actuals = actuals or {"group_results": {}, "knockout_results": {}}
        fixed_group_results = self._resolve_fixed_group_results(actuals.get("group_results", {}))
        target_gi = self.group_pos[group_name]

        group_order = np.empty((n, self.n_groups, 4), dtype=int)
        group_key = np.empty((n, self.n_groups, 4), dtype=np.int64)
        scorelines = None
        for gi, tidx in enumerate(self._group_indices):
            gname = self.group_letters[gi]
            fixed_pairs = fixed_group_results.get(gname, {})
            if gi == target_gi:
                pts, gf, ga, scorelines = self._simulate_group_capture(n, tidx, fixed_pairs)
            else:
                pts, gf, ga = self._simulate_group(n, tidx, fixed_pairs)
            gd = gf - ga
            key = pts.astype(np.int64) * 1_000_000 + gd.astype(np.int64) * 1_000 + gf.astype(np.int64)
            order = np.argsort(-key, axis=1, kind="stable")
            for pos in range(4):
                group_order[:, gi, pos] = tidx[order[:, pos]]
                group_key[:, gi, pos] = np.take_along_axis(key, order[:, pos:pos+1], axis=1)[:, 0]

        # Which groups' third-placed team is among the best 8 (and so qualifies).
        third_key = group_key[:, :, 2]
        order3 = np.argsort(-third_key, axis=1, kind="stable")
        top8 = order3[:, :8]
        sim_range = np.arange(n)
        third_qualifies = np.zeros((n, self.n_groups), dtype=bool)
        for k in range(8):
            third_qualifies[sim_range, top8[:, k]] = True

        tidx = self._group_indices[target_gi]
        fixed_pairs = fixed_group_results.get(group_name, {})
        matches = []
        for (i, j) in GROUP_MATCH_PAIRS:
            if (i, j) in fixed_pairs:
                continue
            goals_i, goals_j = scorelines[(i, j)]
            gd_ij = (goals_i - goals_j).astype(int)
            matches.append({
                "home": self.team_names[tidx[i]],
                "away": self.team_names[tidx[j]],
                "result": np.sign(gd_ij).astype(int),
                "gd": gd_ij,
            })

        outcomes = {}
        for pos in range(4):
            team_i = int(tidx[pos])
            name = self.team_names[team_i]
            first = group_order[:, target_gi, 0] == team_i
            second = group_order[:, target_gi, 1] == team_i
            third = group_order[:, target_gi, 2] == team_i
            advanced = first | second | (third & third_qualifies[:, target_gi])
            outcomes[name] = {"first": first, "second": second, "advanced": advanced}

        return {"matches": matches, "outcomes": outcomes, "n": n}

    # ------------------------------------------------------------------
    # Group fixtures (display + odds)
    # ------------------------------------------------------------------

    def _build_group_fixtures(self, group_results: dict, live_matches: list | None = None) -> dict:
        live_keys = set()
        live_info = {}
        for entry in (live_matches or []):
            key = frozenset((entry.get("home"), entry.get("away")))
            live_keys.add(key)
            live_info[key] = entry
        fixtures = {}
        for gi, g in enumerate(self.groups):
            gname = g["name"]
            played = {}
            for entry in group_results.get(gname, []):
                key = (entry.get("home"), entry.get("away"))
                played[key] = entry
            matches = []
            for (i, j) in GROUP_MATCH_PAIRS:
                home_name = g["teams"][i]
                away_name = g["teams"][j]
                entry = played.get((home_name, away_name)) or played.get((away_name, home_name))
                match = {"home": home_name, "away": away_name}
                if entry is not None:
                    if entry.get("home") == home_name:
                        match["home_goals"] = int(entry["home_goals"])
                        match["away_goals"] = int(entry["away_goals"])
                    else:
                        match["home_goals"] = int(entry["away_goals"])
                        match["away_goals"] = int(entry["home_goals"])
                    match["played"] = True
                    # Goal/card events (if captured) live on the result entry
                    # and persist after the match finishes.
                    if entry.get("events"):
                        match["events"] = entry["events"]
                    key = frozenset((home_name, away_name))
                    if key in live_keys:
                        match["in_progress"] = True
                        live = live_info.get(key, {})
                        if live.get("minute") is not None:
                            match["minute"] = live["minute"]
                        if live.get("status"):
                            match["status"] = live["status"]
                else:
                    elo_h = float(self.team_elos[self.team_idx[home_name]])
                    elo_a = float(self.team_elos[self.team_idx[away_name]])
                    match["played"] = False
                    match["odds"] = match_outcome_probs(elo_h, elo_a, knockout=False, n=100_000)
                matches.append(match)
            fixtures[gname] = matches
        return fixtures

    def _attach_schedule(self, results: dict) -> None:
        """Attach date/time/venue metadata (from data/wc2026.json 'schedule') to
        each group fixture and bracket match, in-place."""
        schedule = self.data.get("schedule")
        if not schedule:
            return

        for g in self.groups:
            gname = g["name"]
            sched_matches = schedule.get("groups", {}).get(gname, [])
            for match, sm in zip(results["fixtures"].get(gname, []), sched_matches):
                match["date"] = sm["date"]
                match["local_time"] = sm["local_time"]
                match["local_timezone"] = sm["local_timezone"]
                match["venue"] = sm["venue"]
                match["place"] = sm["place"]

        for mno_str, sm in schedule.get("knockout", {}).items():
            m = results["bracket_matches"].get(int(mno_str))
            if m is not None:
                m["date"] = sm["date"]
                m["local_time"] = sm["local_time"]
                m["local_timezone"] = sm["local_timezone"]
                m["venue"] = sm["venue"]
                m["place"] = sm["place"]

    # ------------------------------------------------------------------
    # Knockout stage (real FIFA bracket, matches 73-103)
    # ------------------------------------------------------------------

    def _resolve_third_place_assignments(self, n: int, group_order: np.ndarray, group_key: np.ndarray):
        """
        Returns a dict mapping match_no (74,77,79,80,81,82,85,87) -> (n,) array
        of team indices, the 3rd-placed team assigned to that match's "T" slot
        per the official Annex C table.
        """
        third_team = group_order[:, :, 2]   # (n, 12) team index of 3rd-place per group
        third_key = group_key[:, :, 2]      # (n, 12) ranking key of 3rd-place per group

        order = np.argsort(-third_key, axis=1, kind="stable")  # (n, 12) descending
        top8 = order[:, :8]  # (n, 8) group indices of the 8 best 3rd-placed teams

        # Build 12-bit bitmask: bit g set if group g's 3rd-place team qualifies
        bitmask = np.zeros(n, dtype=int)
        for k in range(8):
            bitmask |= (1 << top8[:, k])

        assign_groups = self._annex_lut[bitmask]  # (n, 8) group indices, ordered per annex_match_order

        # team index for each of the 8 matches
        t_team = np.take_along_axis(third_team, assign_groups, axis=1)  # (n, 8)

        result = {}
        for i, match_no in enumerate(self.annex_match_order):
            result[match_no] = t_team[:, i]
        return result

    def _resolve_slot(self, slot, n, group_order, third_assign, match_winner):
        """
        slot is either:
          - ["W", group_letter] -> winner of that group
          - ["R", group_letter] -> runner-up of that group
          - ["T", match_no]     -> third-place team assigned via Annex C
          - an int match_no     -> winner of that previous match
        Returns (n,) array of team indices.
        """
        if isinstance(slot, list):
            kind, val = slot
            if kind == "W":
                gi = self.group_pos[val]
                return group_order[:, gi, 0]
            elif kind == "R":
                gi = self.group_pos[val]
                return group_order[:, gi, 1]
            elif kind == "T":
                return third_assign[val]
            else:
                raise ValueError(f"Unknown slot kind {kind}")
        else:
            # reference to a previous match's winner
            return match_winner[slot]

    def _simulate_knockout(self, n: int, group_order: np.ndarray, group_key: np.ndarray,
                            fixed_knockout_winners: dict) -> dict:
        n_teams = len(self.team_names)
        sim_range = np.arange(n)

        # reached codes:
        # 1 = qualified for R32 (top 2 of group, or one of best 8 thirds)
        # 2 = won R32 (reached R16)
        # 3 = won R16 (reached QF)
        # 4 = won QF (reached SF)
        # 5 = won SF (reached Final)
        # 7 = won Final (champion)
        reached = np.zeros((n, n_teams), dtype=np.int8)

        third_assign = self._resolve_third_place_assignments(n, group_order, group_key)

        # Mark all R32 participants as qualified (reached >= 1)
        for gi in range(self.n_groups):
            for pos in (0, 1):
                teams = group_order[:, gi, pos]
                reached[sim_range, teams] = np.maximum(reached[sim_range, teams], 1)
        for match_no, teams in third_assign.items():
            reached[sim_range, teams] = np.maximum(reached[sim_range, teams], 1)

        match_winner = {}  # match_no -> (n,) team index of winner
        bracket_matches = {}  # match_no -> info dict (filled in below)

        def record_match(match_no, team_a, team_b, reach_code):
            winner = self._simulate_knockout_match(team_a, team_b)  # 0=a wins, 1=b wins
            if match_no in fixed_knockout_winners:
                aw = fixed_knockout_winners[match_no]
                winner = np.where(team_a == aw, 0, np.where(team_b == aw, 1, winner)).astype(np.int8)
            winning_team = np.where(winner, team_b, team_a)
            match_winner[match_no] = winning_team
            mask_a = winner == 0
            mask_b = winner == 1
            reached[mask_a, team_a[mask_a]] = np.maximum(reached[mask_a, team_a[mask_a]], reach_code)
            reached[mask_b, team_b[mask_b]] = np.maximum(reached[mask_b, team_b[mask_b]], reach_code)
            bracket_matches[match_no] = {"home": team_a, "away": team_b}

        # R32 (matches 73-88) -> reach code 2
        for m in self.r32_defs:
            team_a = self._resolve_slot(m["home"], n, group_order, third_assign, match_winner)
            team_b = self._resolve_slot(m["away"], n, group_order, third_assign, match_winner)
            record_match(m["match"], team_a, team_b, 2)

        # R16 (matches 89-96) -> reach code 3
        for m in self.r16_defs:
            record_match(m["match"], match_winner[m["home"]], match_winner[m["away"]], 3)
        # QF (matches 97-100) -> reach code 4
        for m in self.qf_defs:
            record_match(m["match"], match_winner[m["home"]], match_winner[m["away"]], 4)
        # SF (matches 101-102) -> reach code 5
        for m in self.sf_defs:
            record_match(m["match"], match_winner[m["home"]], match_winner[m["away"]], 5)
        # Final (match 103) -> reach code 7
        record_match(self.final_def["match"], match_winner[self.final_def["home"]],
                      match_winner[self.final_def["away"]], 7)

        results = self._aggregate(n, reached, group_order)
        results["_bracket_matches"] = self._summarize_bracket_matches(n, bracket_matches)
        results["opponent_probs"] = self._compute_opponent_probs(n, bracket_matches)
        return results

    def _simulate_knockout_match(self, team_a: np.ndarray, team_b: np.ndarray) -> np.ndarray:
        """Returns 0 where A wins, 1 where B wins. Draws -> penalty shootout."""
        elo_a = self.team_elos[team_a]
        elo_b = self.team_elos[team_b]
        la, lb = compute_lambdas_vec(elo_a, elo_b)
        goals_a = np.random.poisson(la)
        goals_b = np.random.poisson(lb)

        draw = goals_a == goals_b
        if np.any(draw):
            p_a_pen = penalty_win_prob(elo_a[draw], elo_b[draw])
            pen_wins_a = np.random.random(np.sum(draw)) < p_a_pen
            goals_a = goals_a.copy()
            goals_b = goals_b.copy()
            goals_a[draw] += pen_wins_a.astype(int)
            goals_b[draw] += (~pen_wins_a).astype(int)

        return (goals_b > goals_a).astype(np.int8)

    # ------------------------------------------------------------------
    # Bracket match summaries (for the fixtures/bracket pages)
    # ------------------------------------------------------------------

    def _slot_summary(self, n: int, arr: np.ndarray) -> dict:
        """Summarize a (n,) array of team indices occupying a bracket slot."""
        if np.all(arr == arr[0]):
            tidx = int(arr[0])
            return {
                "determined": True,
                "team": self.team_names[tidx],
                "elo": float(self.team_elos[tidx]),
                "candidates": [],
            }
        counts = np.bincount(arr, minlength=len(self.team_names))
        probs = counts / n
        top_idx = np.argsort(-probs)[:5]
        candidates = [
            {"team": self.team_names[i], "probability": round(float(probs[i]), 4)}
            for i in top_idx if probs[i] > 0
        ]
        return {"determined": False, "team": None, "elo": None, "candidates": candidates}

    def _compute_opponent_probs(self, n: int, bracket_matches: dict) -> dict:
        """For each team and each knockout round, the top-5 most likely
        opponents in that round (conditional on the team reaching it)."""
        rounds = [
            ("Round of 32", self.r32_defs),
            ("Round of 16", self.r16_defs),
            ("Quarterfinals", self.qf_defs),
            ("Semifinals", self.sf_defs),
            ("Final", [self.final_def]),
        ]
        n_teams = len(self.team_names)
        out = {tname: {} for tname in self.team_names}
        for round_name, defs in rounds:
            opp_counts = np.zeros((n_teams, n_teams), dtype=np.int64)
            appearances = np.zeros(n_teams, dtype=np.int64)
            for m in defs:
                home_arr = bracket_matches[m["match"]]["home"]
                away_arr = bracket_matches[m["match"]]["away"]
                np.add.at(opp_counts, (home_arr, away_arr), 1)
                np.add.at(opp_counts, (away_arr, home_arr), 1)
                np.add.at(appearances, home_arr, 1)
                np.add.at(appearances, away_arr, 1)
            for tidx, tname in enumerate(self.team_names):
                total = appearances[tidx]
                if total == 0:
                    continue
                probs = opp_counts[tidx] / total
                top_idx = np.argsort(-probs)[:5]
                opponents = [
                    {"team": self.team_names[i], "probability": round(float(probs[i]), 4)}
                    for i in top_idx if probs[i] > 0
                ]
                if opponents:
                    out[tname][round_name] = opponents
        return out

    def _summarize_bracket_matches(self, n: int, bracket_matches: dict) -> dict:
        out = {}
        for m in self.all_knockout_defs:
            match_no = m["match"]
            home_arr, away_arr = bracket_matches[match_no]["home"], bracket_matches[match_no]["away"]
            home_summary = self._slot_summary(n, home_arr)
            away_summary = self._slot_summary(n, away_arr)
            entry = {
                "match": match_no,
                "round": ROUND_NAMES.get(match_no, ""),
                "home": home_summary,
                "away": away_summary,
                "outcome": None,
                "actual_winner": None,
            }
            if home_summary["determined"] and away_summary["determined"]:
                entry["outcome"] = match_outcome_probs(
                    home_summary["elo"], away_summary["elo"], knockout=True, n=100_000
                )
            out[match_no] = entry
        return out

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate(self, n: int, reached: np.ndarray, group_order: np.ndarray) -> dict:
        group_advance = (reached >= 1).mean(axis=0)
        r16 = (reached >= 2).mean(axis=0)
        qf = (reached >= 3).mean(axis=0)
        sf = (reached >= 4).mean(axis=0)
        final = (reached >= 5).mean(axis=0)
        winner = (reached >= 7).mean(axis=0)

        # Group finish positions (1st/2nd/3rd/4th) from group_order
        finish_prob = np.zeros((4, len(self.team_names)))  # [position][team]
        for gi in range(self.n_groups):
            for pos in range(4):
                teams_at_pos = group_order[:, gi, pos]
                counts = np.bincount(teams_at_pos, minlength=len(self.team_names))
                finish_prob[pos] += counts
        finish_prob /= n

        def to_dict(arr):
            return {self.team_names[i]: round(float(arr[i]), 4) for i in range(len(self.team_names))}

        group_finish = {}
        for gi, g in enumerate(self.groups):
            group_finish[g["name"]] = {}
            for tname in g["teams"]:
                tidx = self.team_idx[tname]
                group_finish[g["name"]][tname] = {
                    "first_prob": round(float(finish_prob[0, tidx]), 4),
                    "second_prob": round(float(finish_prob[1, tidx]), 4),
                    "third_prob": round(float(finish_prob[2, tidx]), 4),
                    "fourth_prob": round(float(finish_prob[3, tidx]), 4),
                    "advance_prob": round(float(group_advance[tidx]), 4),
                    "eliminate_prob": round(float(1 - group_advance[tidx]), 4),
                }

        return {
            "group_advance_prob": to_dict(group_advance),
            "round_of_16_prob": to_dict(r16),
            "quarterfinal_prob": to_dict(qf),
            "semifinal_prob": to_dict(sf),
            "finalist_prob": to_dict(final),
            "winner_prob": to_dict(winner),
            "group_finish": group_finish,
        }

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def groups_info(self) -> list[dict]:
        return self.groups
