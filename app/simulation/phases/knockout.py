"""
Knockout phase: single-elimination rounds where each match's participants
are resolved from prior phases' outputs via a slot reference, and the
winner (simulated, then overridden by a recorded actual result if any)
becomes an input to later rounds.

Generalizes ``SimulationEngine._simulate_knockout`` / ``_resolve_slot`` /
``record_match`` (engine.py:626-732).

Stage marking (replaces the five hardcoded reach-code blocks at
engine.py:667-708): every round marks ALL of its match participants — both
sides, win or lose — with that round's declared ``stage``. This alone
reproduces the full ladder with no special-casing, because round N's
participant set is BY CONSTRUCTION round N-1's winner set (a later round's
slots reference ``match_winner[prior_match_no]``, so a team that lost round
N-1 never appears as a participant of round N). The one true special case is
the champion: the final round's WINNER (not just its participants) is
additionally marked with ``winner_stage``.

Slot references (unchanged vocabulary from data/wc2026.json's bracket defs):
  ``["W", group_letter]``  -> that group's winner  (round_robin position 0)
  ``["R", group_letter]``  -> that group's runner-up (round_robin position 1)
  ``["T", wildcard_slot]`` -> a wildcard allocator's output for that slot
  ``int match_no``          -> that match's winner, from an earlier round in
                               THIS phase
"""

from __future__ import annotations

import numpy as np

from app.simulation.phases.base import MatchRecord, Phase, PhaseResult, SimContext, SlotOutput
from app.simulation.sports.base import MatchRules


def _slot_summary(n: int, arr: np.ndarray, entry_names: list[str], entry_elos: np.ndarray) -> dict:
    """Summarize a (n,) array of entry indices occupying a bracket slot —
    port of SimulationEngine._slot_summary (engine.py:738-755)."""
    if np.all(arr == arr[0]):
        tidx = int(arr[0])
        return {
            "determined": True,
            "team": entry_names[tidx],
            "elo": float(entry_elos[tidx]),
            "candidates": [],
        }
    counts = np.bincount(arr, minlength=len(entry_names))
    probs = counts / n
    top_idx = np.argsort(-probs)[:5]
    candidates = [
        {"team": entry_names[i], "probability": round(float(probs[i]), 4)}
        for i in top_idx if probs[i] > 0
    ]
    return {"determined": False, "team": None, "elo": None, "candidates": candidates}


class KnockoutRound:
    def __init__(self, round_id: str, stage: str, matches: list[dict]):
        """
        Args:
            round_id: identifier for this round (e.g. "r32").
            stage: the stage code marked on every participant of this round
                (see module docstring — this single value does double duty
                as "reached this round").
            matches: ``[{"number": int | None, "index": int, "home": slot,
                "away": slot}]``. ``number`` is an EXTERNAL match number
                (WC-style, e.g. 73-103) when the format has one; ``index``
                is this match's position within the round (0-based) and is
                what a generated bracket (see ``generate_single_elimination``
                below) uses to address a match that has no external number.
        """
        self.round_id = round_id
        self.stage = stage
        self.matches = matches


def generate_single_elimination(n_seats: int, round_ids: list[str] | None = None) -> list[KnockoutRound]:
    """Build a standard power-of-2 single-elimination bracket from ``n_seats``
    seeded/drawn positions: seat ``2i`` plays seat ``2i+1`` in round 1, and
    each later round's match ``i`` is the winners of the previous round's
    matches ``2i`` and ``2i+1``. No external match numbers are assigned —
    matches are addressed by ``(round_id, index)``, resolved via
    ``KnockoutPhase._resolve_slot``'s bare-tuple branch.

    This is what a real Grand Slam-style draw needs (128 seeded/drawn
    positions, no bespoke bracket layout to hand-author) — unlike WC2026,
    whose R32 pairing is irregular (Annex C best-thirds wildcards mixed in)
    and stays hand-written in data/wc2026.json.

    Args:
        n_seats: number of entrants; must be a power of 2.
        round_ids: optional explicit round-id list, most rounds first
            (e.g. ``["r128","r64","r32","r16","qf","sf","final"]``). Default
            is ``r<seats-remaining-after-this-round>`` for every round,
            e.g. ``r64`` for the round that leaves 64 players remaining.
    """
    if n_seats < 2 or (n_seats & (n_seats - 1)) != 0:
        raise ValueError(f"n_seats={n_seats} must be a power of 2 >= 2")

    n_rounds = n_seats.bit_length() - 1
    if round_ids is None:
        round_ids = []
        remaining = n_seats
        while remaining > 1:
            remaining //= 2
            round_ids.append("final" if remaining == 1 else f"r{remaining}")
    if len(round_ids) != n_rounds:
        raise ValueError(f"round_ids has {len(round_ids)} entries, expected {n_rounds}")

    rounds = []
    prev_round_id = None
    n_matches = n_seats // 2
    for round_id in round_ids:
        matches = []
        for i in range(n_matches):
            if prev_round_id is None:
                home = ["E", 2 * i]
                away = ["E", 2 * i + 1]
            else:
                home = (prev_round_id, 2 * i)
                away = (prev_round_id, 2 * i + 1)
            matches.append({"number": None, "index": i, "home": home, "away": away})
        rounds.append(KnockoutRound(round_id, stage=round_id, matches=matches))
        prev_round_id = round_id
        n_matches //= 2
    return rounds


class KnockoutPhase(Phase):
    id = "ko"

    def __init__(
        self,
        rounds: list[KnockoutRound],
        rules: MatchRules,
        winner_stage: str,
        wildcard_allocator=None,
        wildcard_source: tuple[list[str], int] | None = None,
    ):
        """
        Args:
            rounds: ordered list of KnockoutRound, earliest first.
            rules: match rules for every knockout match (must use a decider
                that never leaves a draw undecided, e.g. "shootout").
            winner_stage: stage code additionally marked on the FINAL
                round's winner (the champion).
            wildcard_allocator: an allocators.LutBitmaskAllocator (or
                compatible ``.assign(key) -> {slot_id: (n,) group_idx}``),
                or None if this format has no cross-group wildcard.
            wildcard_source: ``(group_letters, wildcard_position)`` — which
                round_robin outputs to feed the allocator.
        """
        self.rounds = rounds
        self.rules = rules
        self.winner_stage = winner_stage
        self.wildcard_allocator = wildcard_allocator
        self.wildcard_source = wildcard_source

    def _resolve_wildcards(self, ctx: SimContext) -> dict:
        if self.wildcard_allocator is None:
            return {}
        group_letters, wc_pos = self.wildcard_source
        keys = np.stack(
            [ctx.outputs[("group_pos", g, wc_pos)].rank_key for g in group_letters], axis=1
        )
        entries = np.stack(
            [ctx.outputs[("group_pos", g, wc_pos)].entries for g in group_letters], axis=1
        )
        group_assignment = self.wildcard_allocator.assign(keys)
        out = {}
        for slot_id, group_idx in group_assignment.items():
            team_idx = np.take_along_axis(entries, group_idx.reshape(-1, 1), axis=1)[:, 0]
            out[("wildcard", slot_id)] = SlotOutput(entries=team_idx)
        return out

    def _resolve_slot(self, slot, ctx: SimContext, match_winner: dict) -> np.ndarray:
        if isinstance(slot, list):
            kind, val = slot
            if kind == "W":
                return ctx.outputs[("group_pos", val, 0)].entries
            if kind == "R":
                return ctx.outputs[("group_pos", val, 1)].entries
            if kind == "T":
                return ctx.outputs[("wildcard", val)].entries
            if kind == "E":
                return ctx.outputs[("seat", val)].entries
            raise ValueError(f"unknown slot kind {kind!r}")
        # A bare int (WC's global external match number) or a
        # (round_id, index) tuple (a generated bracket's own addressing,
        # see generate_single_elimination) — both just key match_winner.
        return match_winner[slot]

    def simulate(self, ctx: SimContext) -> PhaseResult:
        sport = ctx.sport
        ko_actuals = ctx.actuals.get("knockout_results", {})

        wildcard_outputs = self._resolve_wildcards(ctx)
        ctx.outputs.update(wildcard_outputs)

        n_entries = len(ctx.entry_names)
        match_winner: dict = {}
        outputs: dict = dict(wildcard_outputs)
        stage_marks: list[tuple[np.ndarray, str]] = []
        matches: list[MatchRecord] = []
        # Per-round opponent accumulation (mirrors _compute_opponent_probs,
        # engine.py:757-791), built incrementally per match so the raw (n,)
        # side_a/side_b arrays never need to be retained after this loop —
        # only the (n_entries, n_entries) count matrix persists.
        opponent_data: dict[str, dict] = {
            rnd.round_id: {
                "opp_counts": np.zeros((n_entries, n_entries), dtype=np.int64),
                "appearances": np.zeros(n_entries, dtype=np.int64),
            }
            for rnd in self.rounds
        }

        for rnd in self.rounds:
            od = opponent_data[rnd.round_id]
            for m in rnd.matches:
                side_a = self._resolve_slot(m["home"], ctx, match_winner)
                side_b = self._resolve_slot(m["away"], ctx, match_winner)
                mno = m.get("number")
                # External match number when the format has one (WC);
                # otherwise (round_id, index) — stable and known up front,
                # unlike id(m), so a LATER round's slot can reference it
                # before this match has even been simulated.
                match_key = mno if mno is not None else (rnd.round_id, m["index"])

                elo_a = ctx.entry_elos[side_a]
                elo_b = ctx.entry_elos[side_b]
                outcome = sport.simulate_h2h(elo_a, elo_b, self.rules, ctx.rng)
                if np.any(outcome.winner == -1):
                    raise ValueError(
                        f"knockout match {match_key}: decider left an undecided draw — "
                        f"rules.decider={self.rules.decider!r} must always resolve a winner"
                    )
                winner01 = outcome.winner

                if mno is not None:
                    actual_winner_name = ko_actuals.get(str(mno))
                else:
                    # Generated-bracket addressing: actuals keyed by the
                    # string "round_id:index" (no external match number to
                    # key by, unlike WC).
                    actual_winner_name = ko_actuals.get(f"{rnd.round_id}:{m['index']}")
                if actual_winner_name is not None and actual_winner_name in ctx.entry_idx:
                    aw = ctx.entry_idx[actual_winner_name]
                    # Simulate first (for scoreline stats), then override —
                    # mirrors engine.py:678-682 exactly, including its
                    # documented fallback: a no-op wherever the forced team
                    # occupies neither slot for that simulation.
                    winner01 = np.where(
                        side_a == aw, 0, np.where(side_b == aw, 1, winner01)
                    ).astype(np.int8)

                winning_team = np.where(winner01 == 0, side_a, side_b)
                match_winner[match_key] = winning_team

                np.add.at(od["opp_counts"], (side_a, side_b), 1)
                np.add.at(od["opp_counts"], (side_b, side_a), 1)
                np.add.at(od["appearances"], side_a, 1)
                np.add.at(od["appearances"], side_b, 1)

                stage_marks.append((side_a, rnd.stage))
                stage_marks.append((side_b, rnd.stage))
                if rnd is self.rounds[-1]:
                    stage_marks.append((winning_team, self.winner_stage))

                matches.append(self._build_match_record(
                    ctx, rnd, m, side_a, side_b, outcome, actual_winner_name, mno
                ))

        return PhaseResult(outputs=outputs, stage_marks=stage_marks, matches=matches,
                            extra={"match_winner": match_winner, "opponent_data": opponent_data})

    def _build_match_record(self, ctx, rnd, m, side_a, side_b, outcome, actual_winner_name, mno):
        n = ctx.n
        side_a_summary = _slot_summary(n, side_a, ctx.entry_names, ctx.entry_elos)
        side_b_summary = _slot_summary(n, side_b, ctx.entry_names, ctx.entry_elos)

        outcome_odds = None
        if side_a_summary["determined"] and side_b_summary["determined"]:
            outcome_odds = ctx.sport.outcome_probs(
                side_a_summary["elo"], side_b_summary["elo"], self.rules
            )

        actual = {"winner": actual_winner_name} if actual_winner_name else None
        match_id = ("ko", rnd.round_id, mno) if mno is not None else ("ko", rnd.round_id, m["index"])

        return MatchRecord(
            match_id=match_id,
            phase=self.id,
            round_id=rnd.round_id,
            number=mno,
            side_a=side_a_summary,
            side_b=side_b_summary,
            outcome=outcome_odds,
            actual=actual,
            extra={"index": m.get("index")},
        )
