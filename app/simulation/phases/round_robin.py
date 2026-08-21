"""
Round-robin phase: each of several groups of m entries plays a single
round-robin (every pair once), producing a per-group ranking and,
optionally, a cross-group-comparable ``rank_key`` at one distinguished
"wildcard" position (e.g. 3rd place, for an Annex C-style best-thirds
allocation consumed by a later knockout phase).

Generalizes ``SimulationEngine._simulate_group_stage`` /
``_simulate_group_capture`` (engine.py:365-442), which hardcode 4-team
groups and 3-1-0 football scoring, onto any group size and any
``Sport``/``MatchRules`` combination. The tiebreak ranking itself is
``app.simulation.tiebreak.rank_group_h2h`` (already m-generic, validated
against the FIFA rules oracle in tests/golden/test_tiebreak_generic.py).
"""

from __future__ import annotations

import itertools

import numpy as np

from app.simulation.phases.base import MatchRecord, Phase, PhaseResult, SimContext, SlotOutput
from app.simulation.sports.base import MatchOutcome, MatchRules
from app.simulation.tiebreak import rank_group_h2h

# Every per-simulation group array below is (n, m) — with n=250,000 the dtype
# choice dominates the whole run's peak memory, and these arrays are RETAINED
# in `standings` for all groups until the run ends. int16 is chosen, not int32:
# the values are entry indices (< 32k entrants), points (≤ 3 per match), and
# per-team stat totals over m-1 matches (goals: tens) — all far inside
# int16's ±32,767, while a 128-entrant draw still fits the index range.
# Accumulating an int64 operand into an int16 array is a "same_kind" cast,
# which NumPy performs in place without complaint; and `keys.pack_key` casts
# up to int64 before it multiplies, so the narrower input cannot overflow the
# packed sort key.
_GROUP_DTYPE = np.int16


class RoundRobinPhase(Phase):
    id = "groups"

    def __init__(
        self,
        group_letters: list[str],
        group_size: int,
        match_order: list[tuple[int, int]] | None = None,
        rules: MatchRules | None = None,
        tiebreak_stat: str = "goals",
        wildcard_position: int | None = None,
    ):
        self.group_letters = group_letters
        self.group_size = group_size
        self.match_order = match_order or list(itertools.combinations(range(group_size), 2))
        self.rules = rules or MatchRules(decider="draw")
        self.tiebreak_stat = tiebreak_stat
        # 0-based final-ranking position that should carry a rank_key for
        # cross-group wildcard comparison (e.g. 2 for "3rd place" in a
        # top-2-plus-thirds format). None disables it.
        self.wildcard_position = wildcard_position

    def simulate(self, ctx: SimContext) -> PhaseResult:
        n = ctx.n
        m = self.group_size
        sport = ctx.sport
        stat_names = sport.stat_names()
        if self.tiebreak_stat not in stat_names:
            raise ValueError(
                f"tiebreak_stat={self.tiebreak_stat!r} not in sport.stat_names()={stat_names!r}"
            )

        group_actuals = ctx.actuals.get("group_results", {})

        outputs: dict = {}
        matches: list[MatchRecord] = []
        standings: dict = {}

        for letter in self.group_letters:
            pos_entries = np.stack(
                [ctx.outputs[("group_slot", letter, pos)].entries for pos in range(m)], axis=1
            ).astype(_GROUP_DTYPE)  # (n, m)

            # Name -> local position. Stage 1 only supports a per-run-static
            # group composition (see StaticGroupsSeeding), so position 0's
            # first row is representative of every simulation.
            pos_of_name = {ctx.entry_names[int(pos_entries[0, pos])]: pos for pos in range(m)}

            fixed_outcomes: dict[tuple[int, int], MatchOutcome] = {}
            actual_by_pair: dict[tuple[int, int], dict] = {}
            for entry in group_actuals.get(letter, []):
                home, away = entry.get("home"), entry.get("away")
                if home not in pos_of_name or away not in pos_of_name:
                    continue
                hp, ap = pos_of_name[home], pos_of_name[away]
                for (i, j) in self.match_order:
                    if {i, j} != {hp, ap}:
                        continue
                    hg, ag = int(entry["home_goals"]), int(entry["away_goals"])
                    gi_val, gj_val = (hg, ag) if i == hp else (ag, hg)
                    goals_i = np.full(n, gi_val, dtype=_GROUP_DTYPE)
                    goals_j = np.full(n, gj_val, dtype=_GROUP_DTYPE)
                    winner = np.where(
                        goals_i > goals_j, 0, np.where(goals_i < goals_j, 1, -1)
                    ).astype(np.int8)
                    drew = goals_i == goals_j
                    fixed_outcomes[(i, j)] = MatchOutcome(
                        winner=winner, stats={"goals": (goals_i, goals_j)}, drew=drew
                    )
                    actual_by_pair[(i, j)] = entry
                    break

            pts = np.zeros((n, m), dtype=_GROUP_DTYPE)
            stat_for = {s: np.zeros((n, m), dtype=_GROUP_DTYPE) for s in stat_names}
            stat_against = {s: np.zeros((n, m), dtype=_GROUP_DTYPE) for s in stat_names}
            scorelines: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}

            for (i, j) in self.match_order:
                home_name = ctx.entry_names[int(pos_entries[0, i])]
                away_name = ctx.entry_names[int(pos_entries[0, j])]
                is_fixed = (i, j) in fixed_outcomes

                if is_fixed:
                    outcome = fixed_outcomes[(i, j)]
                else:
                    elo_i = ctx.entry_elos[pos_entries[:, i]]
                    elo_j = ctx.entry_elos[pos_entries[:, j]]
                    outcome = sport.simulate_h2h(elo_i, elo_j, self.rules, ctx.rng)

                pts_i, pts_j = sport.points_for(outcome, self.rules)
                pts[:, i] += pts_i
                pts[:, j] += pts_j
                for stat, (si, sj) in outcome.stats.items():
                    stat_for[stat][:, i] += si
                    stat_for[stat][:, j] += sj
                    stat_against[stat][:, i] += sj
                    stat_against[stat][:, j] += si
                scorelines[(i, j)] = outcome.stats[self.tiebreak_stat]

                if is_fixed:
                    entry = actual_by_pair[(i, j)]
                    actual = {"home": entry.get("home"), "away": entry.get("away"),
                              "home_goals": entry.get("home_goals"), "away_goals": entry.get("away_goals")}
                    outcome_odds = None
                else:
                    elo_i0 = float(ctx.entry_elos[int(pos_entries[0, i])])
                    elo_j0 = float(ctx.entry_elos[int(pos_entries[0, j])])
                    actual = None
                    outcome_odds = sport.outcome_probs(elo_i0, elo_j0, self.rules)

                matches.append(MatchRecord(
                    match_id=("groups", letter, i, j),
                    phase=self.id,
                    round_id=None,
                    number=None,
                    side_a={"team": home_name}, side_b={"team": away_name},
                    outcome=outcome_odds,
                    actual=actual,
                    extra={"group": letter},
                ))

            gf = stat_for[self.tiebreak_stat]
            ga = stat_against[self.tiebreak_stat]
            order, key = rank_group_h2h(n, pts, gf, ga, scorelines, m)

            for pos in range(m):
                entries_at_pos = np.take_along_axis(pos_entries, order[:, pos:pos + 1], axis=1)[:, 0]
                rank_key = key[:, pos] if pos == self.wildcard_position else None
                outputs[("group_pos", letter, pos)] = SlotOutput(entries=entries_at_pos, rank_key=rank_key)

            standings[letter] = {
                "positions": pos_entries,  # (n, m) entry idx at each ORIGINAL position
                "order": order,             # (n, m) original-position index, best to worst
                "pts": pts,
                f"{self.tiebreak_stat}_for": gf,
                f"{self.tiebreak_stat}_against": ga,
            }

        return PhaseResult(outputs=outputs, stage_marks=[], matches=matches,
                            extra={"standings": standings})
