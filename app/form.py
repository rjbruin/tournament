"""
"Form" — a per-team indicator of whether a team has been over- or
under-performing relative to what their Elo rating would predict, based on
group-stage results entered so far.

For every played group-stage match, we compare the actual points earned
(win=1, draw=0.5, loss=0) against the *expected* points given the two teams'
Elo ratings (via ``match_outcome_probs``). The average divergence (actual -
expected) is shrunk towards zero based on the number of matches played (so
one fluke result doesn't swing the badge wildly), then scaled into an
"Elo modifier" — a small positive/negative number that can be displayed as a
badge next to a team's name.
"""

from app.simulation.probability import match_outcome_probs

# Number of "phantom" matches assumed at zero divergence, used to shrink the
# observed average divergence towards zero when little evidence is available.
_SHRINKAGE_K = 2.0

# Scales the (shrunk) average points divergence (-1..1) into an Elo-like
# modifier for display.
_SCALE = 120.0

# Cache of expected points per (elo_a, elo_b) pair within a single call,
# since the same fixtures are evaluated for both participants.
_OUTCOME_SAMPLES = 2000


def compute_form(actuals: dict, engine) -> dict[str, float]:
    """Returns {team_name: elo_modifier} for every team with at least one
    played group-stage match. Teams with no played matches are omitted
    (treated as neutral / no badge)."""
    group_results = (actuals or {}).get("group_results", {})

    # team -> list of (actual_points, expected_points)
    divergences: dict[str, list[float]] = {}
    expected_cache: dict[tuple[float, float], float] = {}

    for matches in group_results.values():
        for m in matches:
            home, away = m.get("home"), m.get("away")
            if home not in engine.team_idx or away not in engine.team_idx:
                continue
            try:
                hg, ag = int(m["home_goals"]), int(m["away_goals"])
            except (KeyError, TypeError, ValueError):
                continue

            elo_h = float(engine.team_elos[engine.team_idx[home]])
            elo_a = float(engine.team_elos[engine.team_idx[away]])

            key = (round(elo_h, 1), round(elo_a, 1))
            if key not in expected_cache:
                probs = match_outcome_probs(elo_h, elo_a, knockout=False, n=_OUTCOME_SAMPLES)
                expected_cache[key] = probs["home_win"] + 0.5 * probs["draw"]
            exp_home = expected_cache[key]
            exp_away = 1.0 - exp_home  # draws contribute 0.5 to each side

            if hg > ag:
                act_home, act_away = 1.0, 0.0
            elif hg < ag:
                act_home, act_away = 0.0, 1.0
            else:
                act_home, act_away = 0.5, 0.5

            divergences.setdefault(home, []).append(act_home - exp_home)
            divergences.setdefault(away, []).append(act_away - exp_away)

    form: dict[str, float] = {}
    for team, diffs in divergences.items():
        n = len(diffs)
        avg = sum(diffs) / n
        weight = n / (n + _SHRINKAGE_K)
        form[team] = round(avg * weight * _SCALE, 1)
    return form
