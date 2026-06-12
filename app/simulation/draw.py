"""
Simulates the 2026 FIFA World Cup final draw.

48 teams are split into 4 pots of 12. One team from each pot is drawn into
each of the 12 groups (A-L), giving every group one team from each pot
(pot 1 = position 1, pot 2 = position 2, etc).

Constraints (per the real draw procedure):
  - Hosts (Mexico, Canada, USA) are pre-seeded into A1, B1, D1.
  - The #1/#2 ranked teams (Spain, Argentina) and the #3/#4 ranked teams
    (France, England) are drawn into opposite halves of the bracket
    (groups A-F vs. G-L), so they can only meet in the final.
  - No group may contain more than one team from the same confederation,
    except UEFA, which (having more than 12 qualifiers) may have up to two
    teams in a group.

This module is intentionally independent of ``SimulationEngine`` — it only
produces group compositions (``{letter: [pot1_team, pot2_team, pot3_team,
pot4_team]}``), which the engine can then run a full tournament simulation
on (see ``SimulationEngine.run(..., groups=...)``).
"""

import json
import os
import random

GROUP_LETTERS = list("ABCDEFGHIJKL")
HALF_A = set("ABCDEF")
HALF_B = set("GHIJKL")

_MAX_ATTEMPTS = 5000


def load_draw_pots() -> dict:
    path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "draw_pots.json")
    with open(path) as f:
        return json.load(f)


def _half(letter: str) -> str:
    return "A" if letter in HALF_A else "B"


def simulate_draw(pots: list[list[str]], confederations: dict, host_groups: dict,
                   rival_pairs: list, fixed: dict | None = None,
                   rng: random.Random | None = None) -> dict:
    """Simulate one full draw.

    ``fixed`` (optional): a partial ``{letter: [team_or_None, ...]}`` —
    teams already placed are kept, and only the remaining (None) slots are
    filled randomly. Used to complete a partially-finished draw.

    Returns ``{letter: [pot1_team, pot2_team, pot3_team, pot4_team]}``.
    """
    rng = rng or random
    fixed = fixed or {}

    for overall_attempt in range(_MAX_ATTEMPTS):
        try:
            return _attempt_draw(pots, confederations, host_groups, rival_pairs, fixed, rng)
        except RuntimeError:
            if overall_attempt == _MAX_ATTEMPTS - 1:
                raise
            continue


def _attempt_draw(pots, confederations, host_groups, rival_pairs, fixed, rng):
    # groups[letter][pot_index] = team name or None
    groups: dict[str, list[str | None]] = {
        letter: list(fixed.get(letter, [None, None, None, None])) for letter in GROUP_LETTERS
    }
    for letter in GROUP_LETTERS:
        while len(groups[letter]) < 4:
            groups[letter].append(None)

    placed = {t for slots in groups.values() for t in slots if t}

    for pot_idx, pot in enumerate(pots):
        remaining_teams = [t for t in pot if t not in placed]
        empty_slots = [letter for letter in GROUP_LETTERS if groups[letter][pot_idx] is None]

        if not empty_slots:
            continue

        if pot_idx == 0:
            # Hosts are pre-seeded; remove them and their groups from the
            # random pool (they're typically already "fixed", but handle
            # the from-scratch case too).
            for team, letter in host_groups.items():
                if team in remaining_teams and groups[letter][0] is None:
                    groups[letter][0] = team
                    remaining_teams.remove(team)
                    placed.add(team)
            empty_slots = [letter for letter in GROUP_LETTERS if groups[letter][0] is None]

            for attempt in range(200):
                shuffled = remaining_teams[:]
                slots = empty_slots[:]
                rng.shuffle(shuffled)
                rng.shuffle(slots)
                assignment = dict(zip(slots, shuffled))
                ok = True
                for a, b in rival_pairs:
                    # Resolve each rival's (eventual) group letter.
                    letter_a = _team_letter(groups, assignment, 0, a)
                    letter_b = _team_letter(groups, assignment, 0, b)
                    if letter_a and letter_b and _half(letter_a) == _half(letter_b):
                        ok = False
                        break
                if ok:
                    for letter, team in assignment.items():
                        groups[letter][0] = team
                    break
            else:
                raise RuntimeError("Could not satisfy pot 1 / opposite-half constraints.")
        else:
            base = {letter: list(groups[letter]) for letter in GROUP_LETTERS}
            assignment = _assign_pot(remaining_teams, empty_slots, base, pot_idx, confederations, rng)
            if assignment is None:
                raise RuntimeError(f"Could not satisfy confederation constraints for pot {pot_idx + 1}.")
            for letter, team in assignment.items():
                base[letter][pot_idx] = team
            groups = base

        placed = {t for slots in groups.values() for t in slots if t}

    return groups


def _assign_pot(teams, slots, base, pot_idx, confederations, rng):
    """Randomized backtracking: assign each team in ``teams`` to a distinct
    slot in ``slots`` such that no group (``base[letter]``) ends up with two
    teams from the same confederation (UEFA may have up to two). Returns
    ``{letter: team}`` or ``None`` if no valid assignment exists."""
    teams = teams[:]
    slots = slots[:]
    rng.shuffle(teams)
    rng.shuffle(slots)

    def backtrack(i, remaining_slots, used):
        if i == len(teams):
            return {}
        team = teams[i]
        conf = confederations.get(team)
        candidates = remaining_slots[:]
        rng.shuffle(candidates)
        for letter in candidates:
            existing = [confederations.get(t) for t in base[letter] if t]
            existing += [confederations.get(t) for l, t in used.items() if l == letter]
            count = existing.count(conf)
            if count >= 1 and not (conf == "UEFA" and count < 2):
                continue
            used[letter] = team
            rest = backtrack(i + 1, [s for s in remaining_slots if s != letter], used)
            if rest is not None:
                rest[letter] = team
                return rest
            del used[letter]
        return None

    result = backtrack(0, slots, {})
    return result


def _team_letter(groups, assignment, pot_idx, team):
    for letter in GROUP_LETTERS:
        if groups[letter][pot_idx] == team:
            return letter
    for letter, t in assignment.items():
        if t == team:
            return letter
    return None


def simulate_many_draws(n: int, fixed: dict | None = None, seed: int | None = None) -> list[dict]:
    """Run ``n`` independent draw simulations and return the list of
    resulting group compositions."""
    data = load_draw_pots()
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        out.append(simulate_draw(data["pots"], data["confederations"], data["host_groups"],
                                  data["rival_pairs"], fixed=fixed, rng=rng))
    return out


def opponent_stats(draws: list[dict]) -> dict:
    """For each team, the probability of being drawn into a group with each
    other team (across the given list of draws)."""
    n = len(draws)
    stats: dict[str, dict[str, int]] = {}
    for groups in draws:
        for letter, teams in groups.items():
            teams = [t for t in teams if t]
            for t in teams:
                stats.setdefault(t, {})
                for other in teams:
                    if other != t:
                        stats[t][other] = stats[t].get(other, 0) + 1
    return {
        team: {other: round(count / n, 4) for other, count in opponents.items()}
        for team, opponents in stats.items()
    }


def is_draw_complete(draw: dict | None) -> bool:
    if not draw:
        return False
    return all(
        letter in draw and len(draw[letter]) == 4 and all(draw[letter])
        for letter in GROUP_LETTERS
    )
