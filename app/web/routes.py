import os

from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash, session, Response
from flask_login import current_user, login_required

import app as app_module
from app import auth, data_store
from app.web.view_helpers import normalize_group_match, normalize_bracket_match, compute_group_table, utc_sort_key as _utc_sort_key

web_bp = Blueprint("web", __name__)


@web_bp.before_request
def _track_pageview():
    from flask_login import current_user as _cu
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    username = _cu.username if getattr(_cu, "is_authenticated", False) else None
    try:
        data_store.record_pageview(ip, request.path, username)
    except Exception:
        pass


@web_bp.get("/manifest.json")
def manifest():
    import json
    data = {
        "name": "WC 2026 Simulator",
        "short_name": "WC 2026",
        "description": "Monte Carlo simulation of the 2026 FIFA World Cup",
        "start_url": url_for("web.index"),
        "display": "standalone",
        "background_color": "#1a1a2e",
        "theme_color": "#2e7d32",
        "icons": [
            {"src": url_for("static", filename="icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": url_for("static", filename="icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    return Response(json.dumps(data), mimetype="application/manifest+json")


def _admin_users_with_usage() -> list[dict]:
    users = auth.list_users()
    for u in users:
        u["llm_usage"] = data_store.get_llm_usage(u["username"])
    return users


def _is_live(match: dict) -> bool:
    """A match is "live" if it's flagged in_progress, or if the current
    time is within 2 hours of its scheduled kickoff."""
    if match.get("in_progress"):
        return True
    from datetime import datetime, timedelta, timezone
    start = _utc_sort_key(match)
    if start == datetime.min:
        return False
    now = datetime.now(timezone.utc)
    return start <= now <= start + timedelta(hours=2)


def _results_up_to_date(engine) -> bool:
    """True if every match whose kickoff is already in the past has a
    recorded result. When a started match is still missing its result, a
    results update is warranted (returns False)."""
    from datetime import datetime, timezone
    from app.simulation.engine import GROUP_MATCH_PAIRS

    now = datetime.now(timezone.utc)
    actuals = data_store.load_actuals()
    schedule = engine.data.get("schedule", {})

    played_pairs = {
        gname: {frozenset((e.get("home"), e.get("away"))) for e in entries}
        for gname, entries in actuals.get("group_results", {}).items()
    }
    for g in engine.groups:
        gname = g["name"]
        sched = schedule.get("groups", {}).get(gname, [])
        for (i, j), sm in zip(GROUP_MATCH_PAIRS, sched):
            kickoff = _utc_sort_key(sm)
            if kickoff == datetime.min or kickoff > now:
                continue
            if frozenset((g["teams"][i], g["teams"][j])) not in played_pairs.get(gname, set()):
                return False

    ko_results = actuals.get("knockout_results", {})
    for mno_str, sm in schedule.get("knockout", {}).items():
        kickoff = _utc_sort_key(sm)
        if kickoff == datetime.min or kickoff > now:
            continue
        if mno_str not in ko_results and int(mno_str) not in ko_results:
            return False

    return True


def _advance_prob_before(engine, actuals, group_name, pairs, n=30_000):
    """Run a mini simulation with the given match pairs removed from actuals
    and return group_advance_prob for all teams (used to show odds deltas).
    ``pairs`` is a list of (home, away) tuples to exclude."""
    import copy
    before = copy.deepcopy(actuals)
    excluded = {frozenset(p) for p in pairs}
    before.setdefault("group_results", {})[group_name] = [
        r for r in before["group_results"].get(group_name, [])
        if frozenset([r.get("home"), r.get("away")]) not in excluded
    ]
    before["live_matches"] = [
        lm for lm in before.get("live_matches", [])
        if frozenset([lm.get("home"), lm.get("away")]) not in excluded
    ]
    try:
        return engine.run(n, actuals=before).get("group_advance_prob", {})
    except Exception:
        return {}


def _advance_prob_after(engine, actuals, group_name, raw_fixtures, cutoff_sort_key, n=30_000):
    """Run a mini simulation with only group results up to and including cutoff_sort_key,
    returning group_advance_prob for all teams (used on the match page for completed matches)."""
    import copy
    after = copy.deepcopy(actuals)
    later_pairs = {
        frozenset([m.get("home"), m.get("away")])
        for m in raw_fixtures
        if _utc_sort_key(m) > cutoff_sort_key
    }
    after.setdefault("group_results", {})[group_name] = [
        r for r in after["group_results"].get(group_name, [])
        if frozenset([r.get("home"), r.get("away")]) not in later_pairs
    ]
    after["live_matches"] = [
        lm for lm in after.get("live_matches", [])
        if frozenset([lm.get("home"), lm.get("away")]) not in later_pairs
    ]
    try:
        return engine.run(n, actuals=after).get("group_advance_prob", {})
    except Exception:
        return {}


def _knocked_out_teams(results) -> set:
    """Return team names eliminated in any completed knockout match."""
    knocked_out = set()
    if not results or "bracket_matches" not in results:
        return knocked_out
    for m in results["bracket_matches"].values():
        winner = m.get("actual_winner")
        if not winner:
            continue
        for side in ("home", "away"):
            slot = m.get(side, {})
            if slot.get("determined") and slot.get("team") and slot["team"] != winner:
                knocked_out.add(slot["team"])
    return knocked_out


def _group_table_before(g, raw_fixtures, live_matches, teams_by_name, results):
    """Standings for group `g` as they were before `live_matches` (a list of
    normalized match dicts) were played. Pass a single-element list for the
    original single-match behaviour."""
    import copy
    excluded = [{lm.get("home_team"), lm.get("away_team")} for lm in live_matches]
    before_fixtures = []
    for m in raw_fixtures:
        pair = {m.get("home"), m.get("away")}
        if pair in excluded:
            m = copy.deepcopy(m)
            m["played"] = False
            m.pop("home_goals", None)
            m.pop("away_goals", None)
        before_fixtures.append(m)
    return compute_group_table(g, before_fixtures, teams_by_name, results)


def _scenario_id() -> str:
    """Resolve the active scenario id: the `s` query param (which also
    persists the choice in the session for subsequent pages), falling back
    to the session's last-selected scenario, then "current". Anonymous
    visitors are always pinned to the public "current" scenario."""
    if not current_user.is_authenticated:
        return request.args.get("s") or "current"
    from flask import session
    s = request.args.get("s")
    if s:
        previous = session.get("scenario_id")
        if s != previous:
            # Switching to a different scenario: drop any cached results for
            # it so they're recomputed fresh (e.g. against the latest
            # data/actuals.json for "current") rather than showing whatever
            # was last computed for it, possibly under stale data.
            key = ((_username() or "_anon").lower(), s)
            app_module._simulation_results.pop(key, None)
            # Only one hypothetical "what if" scenario exists at a time, and
            # it's discarded as soon as the user navigates away from it.
            if previous == data_store.HYPOTHETICAL_SCENARIO_ID and s != previous:
                data_store.delete_hypothetical_scenario(_username())
                old_key = ((_username() or "_anon").lower(), data_store.HYPOTHETICAL_SCENARIO_ID)
                app_module._simulation_results.pop(old_key, None)
        session["scenario_id"] = s
        return s
    return session.get("scenario_id") or "current"


def _username():
    return current_user.username if current_user.is_authenticated else None


def _results_for_scenario(scenario_id: str):
    n = None
    if current_user.is_authenticated:
        n = current_user.settings.get("n_simulations")
    return app_module.get_or_run_results(_username(), scenario_id, n=n)


def _is_pre_draw(scenario_id: str) -> bool:
    """True if `scenario_id` is the virtual "pre-draw" scenario, for which
    the draw hasn't taken place — group compositions (and therefore
    fixtures) are just one arbitrary simulated draw and shouldn't be
    displayed as if they were real."""
    return scenario_id == data_store.PRE_DRAW_SCENARIO_ID


def _groups_for_results(engine, results):
    """The group compositions matching `results` (which may have been
    computed with a custom draw override). Falls back to the engine's
    default/real groups if `results` doesn't carry a `group_finish`
    (e.g. no simulation has run yet)."""
    if results and results.get("group_finish"):
        return [
            {"name": letter, "teams": list(results["group_finish"][letter].keys())}
            for letter in engine.group_letters
        ]
    return engine.groups


def _stake_text_explanation(clinch_outcomes, elim_outcomes, clinch_position,
                            third_outcomes=None):
    """Generate a natural-language sentence describing decisive outcomes.

    Covers mathematically certain clinches/eliminations plus outcomes where a
    team is stuck at third place (probabilistic best-third qualification).
    Returns an empty string when nothing decisive is known.
    """
    from app import clinch as _clinch
    _POS_LABEL = {
        _clinch.CLINCHED_FIRST: "in first place",
        _clinch.CLINCHED_TOP2: "in second place",
        _clinch.CLINCHED_THIRD_ADV: "as one of the eight best third-placed teams",
    }
    _CONJ = {"win": "win", "draw": "draw", "loss": "lose"}
    _ORDER = ["win", "draw", "loss"]
    # Threshold to call it "essentially guaranteed" or "essentially impossible"
    _HIGH = 1 - 0.5e-2   # >99%
    _LOW  = 0.5e-2        # <1%

    def _outcome_phrase(outcomes):
        outcomes = [o for o in _ORDER if o in outcomes]
        verbs = [_CONJ[o] for o in outcomes]
        if len(verbs) == 1:
            return verbs[0]
        if len(verbs) == 2:
            return f"{verbs[0]} or {verbs[1]}"
        return "win, draw, or lose"

    parts = []

    # Group clinch outcomes by the resulting position
    from collections import defaultdict
    by_pos = defaultdict(list)
    for o in clinch_outcomes:
        pos = clinch_position.get(o, _clinch.CLINCHED_TOP2)
        by_pos[pos].append(o)

    for pos in [_clinch.CLINCHED_FIRST, _clinch.CLINCHED_TOP2, _clinch.CLINCHED_THIRD_ADV]:
        if pos not in by_pos:
            continue
        label = _POS_LABEL[pos]
        parts.append(f"{_outcome_phrase(by_pos[pos])} to qualify {label}")

    # Third-place outcomes: bucket by qualification likelihood
    if third_outcomes:
        high_third = [o for o, p in third_outcomes.items() if p >= _HIGH]
        low_third  = [o for o, p in third_outcomes.items() if p <= _LOW]
        mid_third  = [o for o in third_outcomes if o not in high_third and o not in low_third]

        if high_third:
            parts.append(f"{_outcome_phrase(high_third)} to qualify as one of the eight best third-placed teams")
        if mid_third:
            parts.append(f"{_outcome_phrase(mid_third)} to place third and wait for other groups")
        if low_third:
            parts.append(f"{_outcome_phrase(low_third)} to be knocked out as one of the four worst third-placed teams")

    if elim_outcomes:
        parts.append(f"{_outcome_phrase(elim_outcomes)} to be knocked out")

    if not parts:
        return ""
    sentence = ", ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


_KO_ROUND_ORDER = {
    "Round of 32": 1,
    "Round of 16": 2,
    "Quarter-finals": 3,
    "Semi-finals": 4,
    "Final": 5,
}


def _team_journey(team, engine, actuals, results, featured_match_no=None):
    """Build a team's tournament journey for the 'How they got here' block.

    Returns::

        {
          "team": str,
          "group_name": str | None,
          "group_place": int | None,
          "group_teams": list[str],
          "knockout_wins": [
            {
              "opponent": str | None,
              "round": str,
              "team_goals": int | None,
              "opp_goals": int | None,
              "team_penalties": int | None,
              "opp_penalties": int | None,
            }, ...
          ],
        }
    """
    # --- Group placement ---
    group_name = None
    group_place = None
    group_teams = []
    teams_by_name = {t["name"]: t for t in engine.data["teams"]}
    for g in engine.groups:
        if team in g["teams"]:
            group_name = g["name"]
            group_teams = list(g["teams"])
            raw_fx = (results or {}).get("fixtures", {}).get(group_name, [])
            try:
                table = compute_group_table(g, raw_fx, teams_by_name, results)
                for row in table:
                    if row["name"] == team:
                        group_place = row["rank"]
                        break
            except Exception:
                pass
            break

    # --- Knockout wins prior to the featured match ---
    ko_results = actuals.get("knockout_results", {})
    ko_scores = actuals.get("knockout_scores", {})
    bm = (results or {}).get("bracket_matches", {})

    featured_round_order = None
    if featured_match_no is not None:
        fm_entry = bm.get(featured_match_no) or bm.get(str(featured_match_no))
        if fm_entry:
            featured_round_order = _KO_ROUND_ORDER.get(fm_entry.get("round", ""), 99)

    knockout_wins = []
    for match_no_str, winner in ko_results.items():
        if winner != team:
            continue
        match_no = int(match_no_str)
        bm_entry = bm.get(match_no) or bm.get(str(match_no))
        if not bm_entry:
            continue

        match_round = bm_entry.get("round", "")
        round_order = _KO_ROUND_ORDER.get(match_round, 0)
        if featured_round_order is not None and round_order >= featured_round_order:
            continue

        home_entry = bm_entry.get("home", {})
        away_entry = bm_entry.get("away", {})
        home_team = home_entry.get("team") if home_entry.get("determined") else None
        away_team = away_entry.get("team") if away_entry.get("determined") else None
        opponent = away_team if home_team == team else home_team
        team_was_home = (home_team == team)

        score = ko_scores.get(str(match_no)) or {}
        hg, ag = score.get("home_goals"), score.get("away_goals")
        hp, ap = score.get("home_penalties"), score.get("away_penalties")
        team_goals = hg if team_was_home else ag
        opp_goals = ag if team_was_home else hg
        team_pens = hp if team_was_home else ap
        opp_pens = ap if team_was_home else hp

        knockout_wins.append({
            "opponent": opponent,
            "round": match_round,
            "round_order": round_order,
            "team_goals": team_goals,
            "opp_goals": opp_goals,
            "team_penalties": team_pens,
            "opp_penalties": opp_pens,
        })

    knockout_wins.sort(key=lambda w: w["round_order"])

    return {
        "team": team,
        "group_name": group_name,
        "group_place": group_place,
        "group_teams": group_teams,
        "knockout_wins": knockout_wins,
    }


def _qualification_notes(engine, scenario_id, featured_fixture, all_normalized):
    """Build "what's at stake" info for the two teams in the featured group
    fixture, from the second group matchday onwards.

    Returns a list of stakes — one entry per team:
      ``{team, status, headline, odds: {win, draw, loss}}``
    where the odds are the chance to advance conditional on each result.

    Empty on the first matchday or for non-group fixtures."""
    from app import qualification

    if not featured_fixture or not featured_fixture.get("_group"):
        return []
    if featured_fixture.get("played") and not featured_fixture.get("in_progress"):
        return []

    gname = featured_fixture["_group"]
    cutoff = featured_fixture["_sort_key"]
    home = featured_fixture.get("home_team")
    away = featured_fixture.get("away_team")
    if not home or not away:
        return []

    # Which matchday is this fixture? Each group plays 6 matches across 3
    # matchdays (2 per matchday), in chronological order. Only show
    # qualification info from matchday 2 onwards.
    group_matches = sorted((m for m in all_normalized if m.get("_group") == gname),
                           key=lambda m: m["_sort_key"])
    fidx = next((i for i, m in enumerate(group_matches)
                 if {m.get("home_team"), m.get("away_team")} == {home, away}), None)
    if fidx is None:
        return []
    matchday = fidx // 2 + 1
    if matchday < 2:
        return []

    # Reconstruct the state *before* this match: every group match that kicked
    # off earlier is kept (using its real result); this match and all later
    # ones are reopened for the reasoning.
    scenario = data_store.load_scenario(scenario_id, _username()) or {}
    actuals = scenario.get("actuals") or data_store._empty_actuals()
    before = {"group_results": {}, "knockout_results": {}, "live_matches": []}
    before_pairs = {(m["_group"], frozenset((m["home_team"], m["away_team"])))
                    for m in all_normalized if m["_sort_key"] < cutoff}
    for g, entries in actuals.get("group_results", {}).items():
        kept = [e for e in entries
                if (g, frozenset((e.get("home"), e.get("away")))) in before_pairs]
        if kept:
            before["group_results"][g] = kept

    # Acute, this-match-framed stakes: headline + per-outcome advance odds.
    info = qualification.match_stakes(engine, before, gname, home, away)
    if info is None:
        return []
    stakes = info["teams"]

    # Overlay *theoretical* (sampling-free) clinch info so the stakes show a ✓
    # only when an outcome mathematically guarantees a top-two finish. The
    # statistical odds remain for the conditional/uncertain cases.
    from app import clinch as _clinch
    g_obj = next((g for g in engine.groups if g["name"] == gname), None)
    if g_obj is not None:
        before_fixtures = [dict(e, played=True)
                           for e in before["group_results"].get(gname, [])]

        # Current (cached) theoretical clinch status — needed to detect
        # CLINCHED_THIRD_ADV, which clinch_after_match cannot compute because it
        # only does within-group reasoning. Once a team has clinched (any path),
        # that status is monotone: no later match can remove it, so the current
        # state is a valid proxy for "before this match."
        _cur_results = _results_for_scenario(scenario_id)
        _cur_clinch = _clinch.clinch_by_team(_cur_results, engine.groups) if _cur_results else {}

        for stake in stakes:
            team = stake["team"]
            opponent = away if team == home else home
            valid_outcomes = [o for o in ("win", "draw", "loss")
                              if stake["odds"].get(o) is not None]

            # Short-circuit: if the team is already certain (including
            # CLINCHED_THIRD_ADV) or already fully eliminated, all outcomes
            # share that status — no per-outcome analysis needed.
            if _clinch.advances_for_sure(_cur_clinch.get(team)):
                stake["clinch_outcomes"] = valid_outcomes
                stake["elim_outcomes"] = []
                stake["clinch_position"] = {o: _cur_clinch.get(team) for o in valid_outcomes}
                stake["third_outcomes"] = {}
                headline, status = qualification._stake_headline(set(valid_outcomes), set())
                stake["headline"] = headline
                stake["status"] = status
                stake["text_explanation"] = ""  # headline already covers certain/impossible
                continue
            if _cur_clinch.get(team) == _clinch.ELIMINATED and not featured_fixture.get("in_progress"):
                stake["clinch_outcomes"] = []
                stake["elim_outcomes"] = valid_outcomes
                stake["clinch_position"] = {}
                stake["third_outcomes"] = {}
                headline, status = qualification._stake_headline(set(), set(valid_outcomes))
                stake["headline"] = headline
                stake["status"] = status
                stake["text_explanation"] = ""
                continue

            # Per-outcome analysis: ✓ when this result mathematically secures
            # top-two (best-third is not decidable per-outcome), ✗ when this
            # result drops the team to 4th regardless of other results.
            clinch_outcomes = []
            elim_outcomes = []
            clinch_position = {}  # outcome -> clinch status string
            third_outcomes = {}   # outcome -> advance odds (float) when stuck at 3rd
            for outcome in valid_outcomes:
                after = _clinch.clinch_after_match(g_obj, before_fixtures, team, opponent, outcome)
                after_status = after.get(team)
                if _clinch.advances_for_sure(after_status):
                    clinch_outcomes.append(outcome)
                    clinch_position[outcome] = after_status
                elif after_status == _clinch.ELIMINATED:
                    elim_outcomes.append(outcome)
                else:
                    # OPEN: check if team is stuck at third place
                    best_pos, worst_pos = _clinch.position_range_after_match(
                        g_obj, before_fixtures, team, opponent, outcome)
                    if best_pos == 3 and worst_pos == 3:
                        third_outcomes[outcome] = stake["odds"].get(outcome) or 0.0
            stake["clinch_outcomes"] = clinch_outcomes
            stake["elim_outcomes"] = elim_outcomes
            stake["clinch_position"] = clinch_position
            stake["third_outcomes"] = third_outcomes
            headline, status = qualification._stake_headline(
                set(clinch_outcomes), set(elim_outcomes))
            stake["headline"] = headline
            stake["status"] = status
            stake["text_explanation"] = _stake_text_explanation(
                clinch_outcomes, elim_outcomes, clinch_position, third_outcomes)

    return stakes


@web_bp.get("/")
def index():
    engine = app_module.get_engine()
    scenario_id = _scenario_id()
    results = _results_for_scenario(scenario_id)
    groups = _groups_for_results(engine, results)
    teams_by_name = {t["name"]: t for t in engine.data["teams"]}

    actuals = data_store.load_actuals()
    ko_scores = actuals.get("knockout_scores", {})

    all_normalized = []
    for g in (groups if not _is_pre_draw(scenario_id) else []):
        raw_fixtures = (results or {}).get("fixtures", {}).get(g["name"], [])
        normalized = [normalize_group_match(m) for m in raw_fixtures]
        for m, raw in zip(normalized, raw_fixtures):
            m["_group"] = g["name"]
            m["_sort_key"] = _utc_sort_key(raw)
            all_normalized.append(m)

    # Include bracket matches so the featured fixture can be a knockout match
    # once all group-stage games have been played.
    bracket_matches_raw = (results or {}).get("bracket_matches", {})
    live_by_pair = {
        frozenset((lm.get("home"), lm.get("away"))): lm
        for lm in actuals.get("live_matches", [])
    }
    if bracket_matches_raw and not _is_pre_draw(scenario_id):
        ko_schedule = engine.data.get("schedule", {}).get("knockout", {})
        for mno, m in bracket_matches_raw.items():
            nm = normalize_bracket_match(m, ko_scores=ko_scores)
            nm["_group"] = None
            sched = ko_schedule.get(str(mno), {})
            nm["_sort_key"] = _utc_sort_key({**m, **sched})
            # Merge live score into in-progress knockout matches.
            pair = frozenset((nm.get("home_team"), nm.get("away_team")))
            lm = live_by_pair.get(pair)
            if lm:
                nm["in_progress"] = True
                nm["played"] = True  # enables score display in the fixture macro
                nm["minute"] = lm.get("minute")
                s = ko_scores.get(str(mno))
                if s:
                    nm["home_goals"] = s.get("home_goals")
                    nm["away_goals"] = s.get("away_goals")
            all_normalized.append(nm)

    # The "current/next fixture" card: prefer an in-progress (live) match,
    # then a fixture without a result yet (upcoming), otherwise fall back to
    # the most recently played one.
    featured_fixture = None
    if all_normalized:
        all_normalized.sort(key=lambda m: m["_sort_key"])
        live = [m for m in all_normalized if m.get("in_progress")]
        upcoming = [m for m in all_normalized if not m.get("played")]
        if live:
            featured_fixture = live[0]
        elif upcoming:
            featured_fixture = upcoming[0]
        else:
            featured_fixture = all_normalized[-1]

    # For the hypothetical scenario, feature the match that was edited
    # (rather than the next-upcoming match), so the Up Next card shows the
    # effects of the "what if" scoreline in the group table.
    if scenario_id == data_store.HYPOTHETICAL_SCENARIO_ID:
        active_scenario_data = data_store.load_scenario(scenario_id, _username())
        fm = (active_scenario_data or {}).get("featured_match")
        if fm:
            match = next((m for m in all_normalized
                          if m.get("_group") == fm.get("group")
                          and {m.get("home_team"), m.get("away_team")} == {fm.get("home"), fm.get("away")}),
                         None)
            if match:
                featured_fixture = match

    # Find the concurrent sibling: matchday 3 has two simultaneous matches per
    # group. If featured_fixture has a same-group match starting within 5 min,
    # include it so both are shown together.
    from datetime import timedelta, datetime as _dt
    def _are_concurrent(m1, m2):
        if m1.get("_group") != m2.get("_group"):
            return False
        k1, k2 = m1["_sort_key"], m2["_sort_key"]
        if k1 == _dt.min or k2 == _dt.min:
            return False
        return abs((k1 - k2).total_seconds()) < 300

    featured_fixtures = []
    if featured_fixture:
        featured_fixtures = [featured_fixture]
        sibling = next(
            (m for m in all_normalized
             if m is not featured_fixture and _are_concurrent(featured_fixture, m)),
            None,
        )
        if sibling:
            featured_fixtures.append(sibling)

    featured_is_live = any(_is_live(m) for m in featured_fixtures)

    featured_group_table = None
    featured_group_table_before = None
    featured_before_adv = None
    if featured_fixtures:
        gname = featured_fixtures[0].get("_group")
        g = next((grp for grp in groups if grp["name"] == gname), None) if gname else None
        if g:
            raw_fixtures = (results or {}).get("fixtures", {}).get(g["name"], [])
            featured_group_table = compute_group_table(g, raw_fixtures, teams_by_name, results)
            pairs = [(m.get("home_team"), m.get("away_team")) for m in featured_fixtures]
            any_live_fx = any(m.get("in_progress") for m in featured_fixtures)
            any_played_fx = any(m.get("played") for m in featured_fixtures)
            if any_live_fx or any_played_fx:
                featured_before_adv = _advance_prob_before(engine, actuals, g["name"], pairs)
                if any_live_fx:
                    live_featured = [m for m in featured_fixtures if m.get("in_progress")]
                    featured_group_table_before = _group_table_before(
                        g, raw_fixtures, live_featured, teams_by_name, results)

    # Previous matches: the most recently played non-live match(es), shown only
    # when the featured fixture is upcoming (not itself a played result).
    previous_fixtures = []
    previous_group_table = None
    previous_before_adv = None
    played_done = [m for m in all_normalized if m.get("played") and not m.get("in_progress")]
    if played_done and featured_fixtures and not featured_fixtures[0].get("played"):
        last_played = played_done[-1]
        previous_fixtures = [last_played]
        prev_sibling = next(
            (m for m in played_done if m is not last_played and _are_concurrent(last_played, m)),
            None,
        )
        if prev_sibling:
            previous_fixtures.append(prev_sibling)
        pg = next((grp for grp in groups if grp["name"] == previous_fixtures[0].get("_group")), None)
        if pg:
            raw_fixtures = (results or {}).get("fixtures", {}).get(pg["name"], [])
            previous_group_table = compute_group_table(pg, raw_fixtures, teams_by_name, results)
            prev_pairs = [(m.get("home_team"), m.get("away_team")) for m in previous_fixtures]
            previous_before_adv = _advance_prob_before(engine, actuals, pg["name"], prev_pairs)

    qualification_stakes = []
    if not _is_pre_draw(scenario_id):
        for fx_match in featured_fixtures:
            if fx_match.get("played") and not fx_match.get("in_progress"):
                continue
            try:
                qualification_stakes.extend(
                    _qualification_notes(engine, scenario_id, fx_match, all_normalized))
            except Exception:
                pass

    # Build "How they got here" journeys for knockout featured fixtures.
    team_journeys = {}
    if featured_fixtures and not featured_fixtures[0].get("_group"):
        fm = featured_fixtures[0]
        featured_match_no = fm.get("match")
        for team in [fm.get("home_team"), fm.get("away_team")]:
            if team:
                try:
                    team_journeys[team] = _team_journey(
                        team, engine, actuals, results, featured_match_no)
                except Exception:
                    pass

    scenario_list = data_store.list_scenarios(_username())
    active_scenario = data_store.load_scenario(scenario_id, _username())
    last_updated_ts = data_store.actuals_last_updated()
    last_updated = None
    if last_updated_ts:
        import time as _time
        last_updated = _time.strftime("%d-%m %H:%M", _time.gmtime(last_updated_ts))

    pending_approvals = 0
    if current_user.is_authenticated and current_user.is_admin:
        pending_approvals = sum(
            1 for u in auth.list_users()
            if not u["approved"] and not u.get("is_admin")
        )

    gs = data_store.load_global_settings()

    pre_draw = _is_pre_draw(scenario_id)
    index_group_tables = {}
    for g in (groups if not pre_draw else []):
        raw_fixtures = (results or {}).get("fixtures", {}).get(g["name"], [])
        index_group_tables[g["name"]] = compute_group_table(g, raw_fixtures, teams_by_name, results)

    return render_template(
        "index.html",
        tournament=engine.data["tournament"],
        teams_by_name=teams_by_name,
        results=results,
        scenario_id=scenario_id,
        active_scenario=active_scenario,
        scenario_list=scenario_list,
        last_updated=last_updated,
        results_up_to_date=_results_up_to_date(engine),
        featured_fixture=featured_fixtures[0] if featured_fixtures else None,
        featured_fixtures=featured_fixtures,
        featured_is_live=featured_is_live,
        live_version=app_module.get_live_status()["version"],
        pending_approvals=pending_approvals,
        invite_only=gs.get("invite_only", True),
        featured_group_table_before=featured_group_table_before,
        featured_group_table=featured_group_table,
        featured_before_adv=featured_before_adv,
        qualification_stakes=qualification_stakes,
        team_journeys=team_journeys,
        previous_fixtures=previous_fixtures,
        previous_fixture=previous_fixtures[0] if previous_fixtures else None,
        previous_group_table=previous_group_table,
        previous_before_adv=previous_before_adv,
        groups=groups,
        group_tables=index_group_tables,
        knocked_out_teams=_knocked_out_teams(results),
    )


@web_bp.get("/groups")
def groups():
    engine = app_module.get_engine()
    scenario_id = _scenario_id()
    results = _results_for_scenario(scenario_id)
    groups = _groups_for_results(engine, results)
    teams_by_name = {t["name"]: t for t in engine.data["teams"]}

    pre_draw = _is_pre_draw(scenario_id)
    group_tables = {}
    group_fixtures = {}
    for g in groups:
        raw_fixtures = [] if pre_draw else (results or {}).get("fixtures", {}).get(g["name"], [])
        group_tables[g["name"]] = compute_group_table(g, raw_fixtures, teams_by_name, results)
        normalized = [normalize_group_match(m) for m in raw_fixtures]
        normalized.sort(key=_utc_sort_key)
        group_fixtures[g["name"]] = normalized

    return render_template(
        "groups.html",
        groups=groups,
        teams_by_name=teams_by_name,
        group_tables=group_tables,
        group_fixtures=group_fixtures,
        results=results,
        scenario_id=scenario_id,
    )


@web_bp.get("/group/<name>")
def group(name: str):
    engine = app_module.get_engine()
    scenario_id = _scenario_id()
    results = _results_for_scenario(scenario_id)
    group = next((g for g in _groups_for_results(engine, results) if g["name"] == name.upper()), None)
    if group is None:
        return redirect(url_for("web.index"))
    teams_by_name = {t["name"]: t for t in engine.data["teams"]}
    return render_template(
        "group.html",
        group=group,
        teams_by_name=teams_by_name,
        results=results,
        scenario_id=scenario_id,
    )


@web_bp.get("/teams")
def teams():
    from app import data_store
    from app.form import compute_form

    engine = app_module.get_engine()

    scenario_id = request.args.get("s") or session.get("scenario_id") or "current"
    scenario = data_store.load_scenario(scenario_id, _username()) or data_store.load_scenario("current")
    try:
        team_form = compute_form(scenario["actuals"], engine)
    except Exception:
        team_form = {}

    teams_list = [dict(t) for t in engine.data["teams"]]  # copy to avoid mutating shared state
    results = _results_for_scenario(scenario_id)
    for t in teams_list:
        t["current_elo"] = t["elo"] + team_form.get(t["name"], 0)
        t["group_advance_prob"] = (results or {}).get("group_advance_prob", {}).get(t["name"])
        t["winner_prob"] = (results or {}).get("winner_prob", {}).get(t["name"])

    favorite_team = None
    if current_user.is_authenticated:
        favorite_team = current_user.settings.get("favorite_team") or None

    knocked_out = _knocked_out_teams(results)
    actuals = data_store.load_actuals()

    # Build per-team elimination info.
    # stage: "group stage 4th" | "group stage 3rd" | knockout round name
    elimination_info: dict[str, dict] = {}

    # Compute group standings to distinguish 4th-place from worst-third knockouts.
    teams_by_name = {t["name"]: t for t in engine.data["teams"]}
    group_position: dict[str, int] = {}  # team -> 1..4 within their group
    for g in engine.groups:
        raw_fx = [] if _is_pre_draw(scenario_id) else (results or {}).get("fixtures", {}).get(g["name"], [])
        rows = compute_group_table(g, raw_fx, teams_by_name, results)
        for i, row in enumerate(rows, start=1):
            group_position[row["name"]] = i

    for t in teams_list:
        adv = t.get("group_advance_prob")
        if adv is not None and adv <= 0 and t["name"] not in knocked_out:
            pos = group_position.get(t["name"], 4)
            stage = "group stage 3rd" if pos == 3 else "group stage 4th"
            elimination_info[t["name"]] = {"stage": stage, "opponent": None}

    tournament_winner = None
    if results and "bracket_matches" in results:
        for m in results["bracket_matches"].values():
            winner = m.get("actual_winner")
            if not winner:
                continue
            if m.get("round") == "Final":
                tournament_winner = winner
            round_name = m.get("round", "")
            for side in ("home", "away"):
                slot = m.get(side, {})
                team = slot.get("team")
                if slot.get("determined") and team and team != winner:
                    elimination_info[team] = {"stage": round_name, "opponent": winner}

    # Tournament rank: only assigned once a team's final placement is determined.
    # All teams from the same eliminated round share the same rank number.
    # Active (still competing) teams get None.
    _ROUND_RANK = {
        "Final": 2,            # loser; winner gets 1 separately
        "Semifinal": 3,        # 3rd/4th — no separate 3rd-place match tracked
        "Quarterfinal": 5,
        "Round of 16": 9,
        "Round of 32": 17,
        "group stage 3rd": 33, # worst 4 third-place finishers
        "group stage 4th": 37, # 12 fourth-place finishers
    }
    # Sort key: how recently a team was knocked out (lower = more recently = shown first).
    _ROUND_SORT = {
        "Final": 0, "Semifinal": 1, "Quarterfinal": 2,
        "Round of 16": 3, "Round of 32": 4,
        "group stage 3rd": 5, "group stage 4th": 6,
    }

    for t in teams_list:
        elim = elimination_info.get(t["name"])
        if t["name"] == tournament_winner:
            t["tournament_rank"] = 1
        elif elim:
            t["tournament_rank"] = _ROUND_RANK.get(elim["stage"])
        else:
            t["tournament_rank"] = None

    def _sort_key(t):
        elim = elimination_info.get(t["name"])
        if t["name"] == tournament_winner:
            return (0, 0, 0)
        elif elim:
            return (1, _ROUND_SORT.get(elim["stage"], 9), -t["current_elo"])
        else:
            return (0, 1, -t["current_elo"])

    teams_sorted = sorted(teams_list, key=_sort_key)

    favorite = next((t for t in teams_sorted if t["name"] == favorite_team), None)

    return render_template(
        "teams.html",
        teams=teams_sorted,
        favorite=favorite,
        knocked_out_teams=knocked_out,
        elimination_info=elimination_info,
    )


@web_bp.get("/team")
def team_default():
    default_team = "Netherlands"
    if current_user.is_authenticated:
        default_team = current_user.settings.get("default_team", "Netherlands")
    return redirect(url_for("web.team", name=default_team, **request.args))


@web_bp.get("/team/<name>")
def team(name: str):
    engine = app_module.get_engine()
    scenario_id = _scenario_id()
    results = _results_for_scenario(scenario_id)
    teams_by_name = {t["name"]: t for t in engine.data["teams"]}
    if name not in teams_by_name:
        return redirect(url_for("web.team_default"))

    team_group = next((g for g in _groups_for_results(engine, results) if name in g["teams"]), None)

    fixtures_for_team = []
    if results and results.get("fixtures") and team_group and not _is_pre_draw(scenario_id):
        for m in results["fixtures"].get(team_group["name"], []):
            if m.get("home") == name or m.get("away") == name:
                fixtures_for_team.append(normalize_group_match(m))
        fixtures_for_team.sort(key=_utc_sort_key)

    bracket_for_team = []
    ko_scores = data_store.load_actuals().get("knockout_scores", {})
    if results and results.get("bracket_matches"):
        for mno, m in results["bracket_matches"].items():
            home = m.get("home", {})
            away = m.get("away", {})
            if home.get("team") == name or away.get("team") == name:
                bracket_for_team.append(normalize_bracket_match(m, ko_scores=ko_scores))
        bracket_for_team.sort(key=lambda m: m.get("match", 0))

    all_team_names = sorted(t["name"] for t in engine.data["teams"])

    # Odds progression across tournament checkpoints: "Start" (pre-draw),
    # then "After group match #N" for each of this team's group matches, then
    # "After <knockout round>" for each round the team has actually played.
    data_store.ensure_match_scenarios()
    checkpoints = data_store.ordered_match_checkpoints(engine)

    actuals_now = data_store.load_actuals()
    played_group_pairs = set()
    for gname, entries in actuals_now.get("group_results", {}).items():
        for e in entries:
            played_group_pairs.add((gname, frozenset((e.get("home"), e.get("away")))))
    ko_played = set()
    for k in actuals_now.get("knockout_results", {}).keys():
        ko_played.add(int(k))

    n = current_user.settings.get("n_simulations") if current_user.is_authenticated else None
    # Historical chart only needs rough odds — use a low N so checkpoint
    # scenarios load fast (10k ≈ 0.5s vs 250k ≈ 4.6s per checkpoint).
    _chart_n = 10_000

    _empty_odds = {"group_advance_prob": None, "winner_prob": None}

    def _odds_for_scenario(sid):
        if sid is None:
            return None
        r = app_module.get_or_run_results(_username(), sid, n=_chart_n)
        if r is None:
            return None
        return {
            "group_advance_prob": r.get("group_advance_prob", {}).get(name, 0),
            "winner_prob": r.get("winner_prob", {}).get(name, 0),
        }

    odds_history = [{"label": "Start", **(_odds_for_scenario(data_store.PRE_DRAW_SCENARIO_ID) or _empty_odds)}]

    if team_group:
        team_group_matches = [
            cp for cp in checkpoints
            if cp["kind"] == "group" and cp["group"] == team_group["name"]
            and name in (cp["home"], cp["away"])
        ]
        for i, cp in enumerate(team_group_matches, start=1):
            played = (cp["group"], frozenset((cp["home"], cp["away"]))) in played_group_pairs
            sid = data_store.match_scenario_id(cp["index"]) if played else None
            odds_history.append({"label": f"After group match {i}", **(_odds_for_scenario(sid) or _empty_odds)})

    round_order = ["Round of 32", "Round of 16", "Quarterfinal", "Semifinal", "Final"]
    bracket_by_round = {m["round"]: m for m in bracket_for_team}
    for rname in round_order:
        m = bracket_by_round.get(rname)
        sid = None
        if m and m.get("match") in ko_played:
            cp = next((c for c in checkpoints if c["kind"] == "knockout" and c["match_no"] == m["match"]), None)
            if cp:
                sid = data_store.match_scenario_id(cp["index"])
        ko_odds = _odds_for_scenario(sid) or _empty_odds
        # Stop tracking group advance prob after the group stage — it's always 1.0 here
        odds_history.append({"label": f"After {rname}", "group_advance_prob": None, "winner_prob": ko_odds["winner_prob"]})

    # Rounds where both teams in the bracket match are already known
    known_ko_rounds = {
        m["round"] for m in bracket_for_team
        if m.get("home_team") and m.get("away_team")
    }


    knocked_out = _knocked_out_teams(results)
    group_stage_complete = bool(fixtures_for_team) and all(m.get("played") for m in fixtures_for_team)
    return render_template(
        "team.html",
        team=teams_by_name[name],
        team_group=team_group,
        all_team_names=all_team_names,
        fixtures_for_team=fixtures_for_team,
        bracket_for_team=bracket_for_team,
        results=results,
        scenario_id=scenario_id,
        odds_history=odds_history,
        knocked_out_teams=knocked_out,
        team_is_knocked_out=(name in knocked_out),
        group_stage_complete=group_stage_complete,
        known_ko_rounds=known_ko_rounds,
    )


@web_bp.get("/bracket")
def bracket():
    engine = app_module.get_engine()
    scenario_id = _scenario_id()
    results = _results_for_scenario(scenario_id)
    if results is None or "bracket_matches" not in results:
        return render_template("bracket.html", results=results, rounds=None, scenario_id=scenario_id)

    bm = results["bracket_matches"]

    # Order each round so that match `2i`/`2i+1` of one round visually feed
    # match `i` of the next round (required by the bracket's connector-line
    # drawing, which assumes that positional relationship). The raw
    # r32/r16/.../final defs aren't necessarily in this order (e.g. R32
    # matches 73/74 don't feed R16 match 89), so derive the display order by
    # walking the bracket backwards from the final.
    r16_by_match = {d["match"]: d for d in engine.r16_defs}
    qf_by_match = {d["match"]: d for d in engine.qf_defs}
    sf_by_match = {d["match"]: d for d in engine.sf_defs}
    final_def = engine.final_def

    order_sf = [final_def["home"], final_def["away"]]
    order_qf = [x for m in order_sf for x in (sf_by_match[m]["home"], sf_by_match[m]["away"])]
    order_r16 = [x for m in order_qf for x in (qf_by_match[m]["home"], qf_by_match[m]["away"])]
    order_r32 = [x for m in order_r16 for x in (r16_by_match[m]["home"], r16_by_match[m]["away"])]

    actuals = data_store.load_actuals()
    ko_scores = actuals.get("knockout_scores", {})
    live_by_pair = {
        frozenset((lm.get("home"), lm.get("away"))): lm
        for lm in actuals.get("live_matches", [])
    }

    def _bracket_match(match_no):
        nm = normalize_bracket_match(bm[match_no], ko_scores=ko_scores)
        pair = frozenset((nm.get("home_team"), nm.get("away_team")))
        lm = live_by_pair.get(pair)
        if lm:
            nm["in_progress"] = True
            nm["minute"] = lm.get("minute")
            # Pull live score from knockout_scores even without an actual_winner yet.
            s = ko_scores.get(str(match_no))
            if s:
                nm["home_goals"] = s.get("home_goals")
                nm["away_goals"] = s.get("away_goals")
        return nm

    rounds_with_scores = [
        (rname, [_bracket_match(m) for m in order])
        for rname, order in [
            ("Round of 32", order_r32),
            ("Round of 16", order_r16),
            ("Quarterfinals", order_qf),
            ("Semifinals", order_sf),
        ]
    ] + [("Final", [_bracket_match(103)])]
    return render_template("bracket.html", results=results, rounds=rounds_with_scores,
                           scenario_id=scenario_id, knocked_out_teams=_knocked_out_teams(results))


@web_bp.get("/fixtures")
def fixtures():
    engine = app_module.get_engine()
    scenario_id = _scenario_id()
    results = _results_for_scenario(scenario_id)
    groups = engine.groups

    # Fixtures are grouped into navigable sections: the three group-stage
    # matchdays, then each knockout round. ``sections`` preserves this
    # canonical order and only includes sections that have fixtures.
    section_defs = [
        ("md1", "Matchday 1", "MD1"),
        ("md2", "Matchday 2", "MD2"),
        ("md3", "Matchday 3", "MD3"),
        ("Round-of-32", "Round of 32", "R32"),
        ("Round-of-16", "Round of 16", "R16"),
        ("Quarterfinal", "Quarterfinals", "QF"),
        ("Semifinal", "Semifinals", "SF"),
        ("Final", "Final", "Final"),
    ]
    buckets = {sid: [] for sid, _, _ in section_defs}

    if results is not None and not _is_pre_draw(scenario_id):
        fixtures_by_group = results.get("fixtures", {})
        for g in groups:
            raw_fixtures = fixtures_by_group.get(g["name"], [])
            # Each group plays 6 matches across 3 matchdays (2 per matchday);
            # assign matchdays by chronological order within the group.
            ordered = sorted(raw_fixtures, key=_utc_sort_key)
            for idx, m in enumerate(ordered):
                matchday = idx // 2 + 1
                nm = normalize_group_match(m)
                nm["header"] = f"Group {g['name']}"
                nm["match_url"] = url_for("web.match_detail", match_no=m["match"]) if m.get("match") else None
                nm["sort_key"] = _utc_sort_key(m)
                buckets[f"md{matchday}"].append(nm)

        bm = results.get("bracket_matches", {})
        ko_scores = data_store.load_actuals().get("knockout_scores", {})
        round_to_section = {
            "Round of 32": "Round-of-32",
            "Round of 16": "Round-of-16",
            "Quarterfinal": "Quarterfinal",
            "Semifinal": "Semifinal",
            "Final": "Final",
        }
        for m in engine.all_knockout_defs:
            match = bm[m["match"]]
            nm = normalize_bracket_match(match, ko_scores=ko_scores)
            nm["header"] = nm["round"]
            nm["match_url"] = url_for("web.match_detail", match_no=nm["match"])
            nm["sort_key"] = _utc_sort_key(match)
            sid = round_to_section.get(nm["round"])
            if sid:
                buckets[sid].append(nm)

        for sid in buckets:
            buckets[sid].sort(key=lambda f: f["sort_key"])

    sections = [
        {"id": sid, "label": label, "short": short, "fixtures": buckets[sid]}
        for sid, label, short in section_defs
        if buckets[sid]
    ]

    return render_template(
        "fixtures.html",
        groups=groups,
        sections=sections,
        results=results,
        scenario_id=scenario_id,
        knocked_out_teams=_knocked_out_teams(results),
    )


@web_bp.get("/match/<int:match_no>")
def match_detail(match_no: int):
    """Dedicated page for a single fixture — identical content to the
    Live Match / Up Next / Latest Result card on the home page."""
    engine = app_module.get_engine()
    scenario_id = _scenario_id()
    results = _results_for_scenario(scenario_id)
    actuals = data_store.load_actuals()
    ko_scores = actuals.get("knockout_scores", {})
    groups = _groups_for_results(engine, results)
    teams_by_name = {t["name"]: t for t in engine.data["teams"]}

    # --- Find the requested fixture ---
    fixture = None
    fixture_group = None

    # Group-stage fixtures
    if results:
        for g in groups:
            for m in results.get("fixtures", {}).get(g["name"], []):
                if m.get("match") == match_no:
                    fixture = normalize_group_match(m)
                    fixture["_group"] = g["name"]
                    fixture["_sort_key"] = _utc_sort_key(m)
                    fixture_group = g
                    break
            if fixture:
                break

    # Knockout fixtures
    if fixture is None and results and "bracket_matches" in results:
        bm = results["bracket_matches"]
        if match_no in bm:
            fixture = normalize_bracket_match(bm[match_no], ko_scores=ko_scores)
            fixture["_group"] = None
            fixture["_sort_key"] = _utc_sort_key(bm[match_no])

    if fixture is None:
        from flask import abort
        abort(404)

    # --- Group table ---
    group_table = None
    group_table_before = None
    group_table_label = None
    before_adv = None
    after_adv = None
    match_clinch = {}
    if fixture_group:
        raw_fixtures = (results or {}).get("fixtures", {}).get(fixture_group["name"], [])
        this_sort_key = fixture.get("_sort_key") or _utc_sort_key(
            next((m for m in raw_fixtures
                  if m.get("home") == fixture.get("home_team") and m.get("away") == fixture.get("away_team")), {}))
        pair = [(fixture.get("home_team"), fixture.get("away_team"))]

        gname = fixture_group["name"]
        if fixture.get("in_progress"):
            # Live: standings with current live score + before-match standings
            before_adv = _advance_prob_before(engine, actuals, gname, pair)
            after_adv = results.get("group_advance_prob", {})  # live state IS the "after"
            after_results = {"group_advance_prob": after_adv}
            group_table = compute_group_table(fixture_group, raw_fixtures, teams_by_name, after_results)
            group_table_label = f"Group {gname} standings — with live score"
            group_table_before = _group_table_before(
                fixture_group, raw_fixtures, [fixture], teams_by_name,
                {"group_advance_prob": before_adv})
            # Clinch is based on truly-finished matches (an in-progress score
            # isn't final), so reason from the state before this match.
            from app import clinch as _clinch_mod
            _pre = [m for m in raw_fixtures
                    if m.get("played") and not m.get("in_progress")
                    and _utc_sort_key(m) < this_sort_key]
            match_clinch = _clinch_mod.clinch_for_group(fixture_group, _pre)
        elif fixture.get("played"):
            # Completed: standings + advance probs after this match only
            before_adv = _advance_prob_before(engine, actuals, gname, pair)
            after_adv = _advance_prob_after(engine, actuals, gname, raw_fixtures, this_sort_key)
            after_fixtures = [m for m in raw_fixtures if _utc_sort_key(m) <= this_sort_key]
            after_results = {"group_advance_prob": after_adv}
            group_table = compute_group_table(fixture_group, after_fixtures, teams_by_name, after_results)
            group_table_label = f"Group {gname} standings — after this match"
            match_clinch = {r["name"]: r["clinch_status"] for r in group_table}
        else:
            # Upcoming: standings as they stand before this match
            before_adv = None
            after_adv = _advance_prob_after(engine, actuals, gname, raw_fixtures, this_sort_key)
            before_fixtures = [m for m in raw_fixtures if _utc_sort_key(m) < this_sort_key]
            before_results = {"group_advance_prob": after_adv}
            group_table = compute_group_table(fixture_group, before_fixtures, teams_by_name, before_results)
            group_table_label = f"Group {gname} standings — before this match"
            match_clinch = {r["name"]: r["clinch_status"] for r in group_table}

    # --- What's at stake ---
    qualification_stakes = []
    if fixture_group and not (fixture.get("played") and not fixture.get("in_progress")):
        # Build all_normalized for _qualification_notes (needs context of full group schedule)
        all_normalized = []
        for g in groups:
            raw = (results or {}).get("fixtures", {}).get(g["name"], [])
            for m in raw:
                nm = normalize_group_match(m)
                nm["_group"] = g["name"]
                nm["_sort_key"] = _utc_sort_key(m)
                all_normalized.append(nm)
        try:
            qualification_stakes = _qualification_notes(engine, scenario_id, fixture, all_normalized)
        except Exception:
            pass

    # --- How they got here / Path to the Cup (knockout matches only) ---
    team_journeys = {}
    if not fixture_group:
        for team in [fixture.get("home_team"), fixture.get("away_team")]:
            if team:
                team_journeys[team] = _team_journey(
                    team, engine, actuals, results, featured_match_no=match_no)

    is_live = fixture.get("in_progress", False)
    can_explore = current_user.is_authenticated and (not fixture.get("played") or is_live)

    # Build a human-readable label: "Match 1 — Group A Matchday 1" or "Match 78 — Round of 32"
    if fixture_group:
        gname = fixture_group["name"]
        raw_group = (results or {}).get("fixtures", {}).get(gname, [])
        ordered_nos = sorted(
            (m.get("match") for m in raw_group if m.get("match")),
            key=lambda x: x
        )
        md_map = {no: (i // 2) + 1 for i, no in enumerate(ordered_nos)}
        md = md_map.get(match_no, "")
        match_label = f"Match {match_no} — Group {gname} Matchday {md}"
    else:
        rnd = fixture.get("round", "")
        match_label = f"Match {match_no} — {rnd}" if rnd else f"Match {match_no}"

    return render_template(
        "match.html",
        match_no=match_no,
        match_label=match_label,
        fixture=fixture,
        fixture_group=fixture_group,
        results=results,
        after_adv=after_adv if fixture_group else None,
        match_clinch=match_clinch,
        scenario_id=scenario_id,
        group_table=group_table,
        group_table_label=group_table_label,
        group_table_before=group_table_before,
        before_adv=before_adv,
        qualification_stakes=qualification_stakes,
        team_journeys=team_journeys,
        is_live=is_live,
        can_explore=can_explore,
        live_version=app_module.get_live_status()["version"],
        knocked_out_teams=_knocked_out_teams(results),
    )


@web_bp.get("/results/manual")
@login_required
def results_manual():
    """A page listing every group-stage fixture with editable score fields,
    for manually entering real-world results when the football-data.org feed
    is slow or incorrect. Saving here overwrites "current"."""
    engine = app_module.get_engine()
    actuals = data_store.load_actuals()
    results = app_module.get_or_run_results(_username(), "current",
                                              n=current_user.settings.get("n_simulations"))

    all_fixtures = []
    fixtures_by_group = (results or {}).get("fixtures", {})
    for g in engine.groups:
        for m in fixtures_by_group.get(g["name"], []):
            nm = normalize_group_match(m)
            nm["group"] = g["name"]
            nm["sort_key"] = _utc_sort_key(m)
            all_fixtures.append(nm)
    all_fixtures.sort(key=lambda f: f["sort_key"])

    return render_template(
        "results_manual.html",
        all_fixtures=all_fixtures,
    )


@web_bp.get("/draw")
def draw():
    from app.simulation.draw import load_draw_pots
    engine = app_module.get_engine()
    pots_data = load_draw_pots()

    actual_groups = {g["name"]: g["teams"] for g in engine.groups}

    username = _username()
    # Compare the real draw *before any matches are played* (the
    # "before the first match" baseline) against the pre-draw average, so the
    # difference reflects the draw itself rather than results played so far.
    post_draw_id = data_store.BEFORE_FIRST_MATCH_SCENARIO_ID
    post_draw_results = app_module.get_or_run_results(username, post_draw_id)
    pre_draw_results = app_module.get_or_run_results(username, "pre-draw")

    comparison = None
    if post_draw_results and pre_draw_results:
        comparison = []
        for t in engine.team_names:
            comparison.append({
                "team": t,
                "current_winner_prob": post_draw_results["winner_prob"].get(t, 0),
                "pre_draw_winner_prob": pre_draw_results["winner_prob"].get(t, 0),
            })
        comparison.sort(key=lambda r: r["current_winner_prob"], reverse=True)

    scenario_list = [s for s in data_store.list_scenarios(_username()) if s.get("draw") is not None or s["id"] == "current"]

    return render_template(
        "draw.html",
        pots=pots_data["pots"],
        host_groups=pots_data["host_groups"],
        rival_pairs=pots_data["rival_pairs"],
        actual_groups=actual_groups,
        group_letters=engine.group_letters,
        comparison=comparison,
        scenarios=scenario_list,
    )


@web_bp.post("/scenarios/new")
@login_required
def scenarios_new():
    label = request.form.get("label", "").strip() or "Untitled scenario"
    base_id = request.form.get("based_on") or "current"
    base = data_store.load_scenario(base_id, _username())
    actuals = (base or {}).get("actuals") or data_store._empty_actuals()
    import copy
    scenario = data_store.fork_scenario(base_id, copy.deepcopy(actuals), label=label, username=current_user.username)
    flash(f"Created scenario '{scenario['label']}'.", "success")
    return redirect(url_for("web.settings"))


@web_bp.post("/scenarios/<scenario_id>/delete")
@login_required
def scenarios_delete(scenario_id):
    if data_store._is_global_scenario_id(scenario_id) and not current_user.is_admin:
        flash("Only the admin can delete this scenario.", "danger")
        return redirect(url_for("web.settings"))
    if data_store.delete_scenario(scenario_id, current_user.username):
        flash("Scenario deleted.", "success")
    else:
        flash("Could not delete that scenario.", "danger")
    return redirect(url_for("web.settings"))


@web_bp.get("/scenarios/compare")
@login_required
def scenario_compare():
    engine = app_module.get_engine()
    scenario_list = data_store.list_scenarios(_username())
    ids = [s["id"] for s in scenario_list]
    a_id = request.args.get("a") or (ids[0] if ids else "current")
    b_id = request.args.get("b") or (ids[1] if len(ids) > 1 else a_id)
    team = request.args.get("team") or current_user.settings.get("default_team", "Netherlands")

    n = current_user.settings.get("n_simulations")

    def _summary(scenario_id):
        results = app_module.get_or_run_results(current_user.username, scenario_id, n=n)
        if results is None:
            return None
        top5 = sorted(results["winner_prob"].items(), key=lambda x: x[1], reverse=True)[:5]
        return {
            "scenario": data_store.load_scenario(scenario_id, current_user.username),
            "top5": top5,
            "team_odds": {
                "group_advance_prob": results["group_advance_prob"].get(team, 0),
                "round_of_16_prob": results["round_of_16_prob"].get(team, 0),
                "quarterfinal_prob": results["quarterfinal_prob"].get(team, 0),
                "semifinal_prob": results["semifinal_prob"].get(team, 0),
                "finalist_prob": results["finalist_prob"].get(team, 0),
                "winner_prob": results["winner_prob"].get(team, 0),
            },
        }

    all_team_names = sorted(t["name"] for t in engine.data["teams"])

    return render_template(
        "scenario_compare.html",
        scenarios=scenario_list,
        a_id=a_id,
        b_id=b_id,
        team=team,
        all_team_names=all_team_names,
        summary_a=_summary(a_id),
        summary_b=_summary(b_id),
    )


@web_bp.get("/simulation-logic")
def simulation_logic():
    return render_template("simulation_logic.html")


@web_bp.get("/changelog")
def changelog():
    from app import changelog as changelog_mod
    return render_template("changelog.html",
                           changelog=changelog_mod.CHANGELOG,
                           app_version=changelog_mod.APP_VERSION)


@web_bp.get("/onboarding")
def onboarding():
    engine = app_module.get_engine()
    all_team_names = sorted(t["name"] for t in engine.data["teams"])
    return render_template(
        "onboarding.html",
        settings=current_user.settings,
        all_team_names=all_team_names,
    )


@web_bp.post("/onboarding")
def onboarding_save():
    n_simulations = request.form.get("n_simulations", "").strip()
    try:
        n_simulations = max(100, min(int(n_simulations), 500_000))
    except ValueError:
        n_simulations = auth.DEFAULT_USER_SETTINGS["n_simulations"]

    auth.update_settings(
        current_user.username,
        default_team=request.form.get("default_team", "").strip() or auth.DEFAULT_USER_SETTINGS["default_team"],
        display_timezone=request.form.get("display_timezone", "").strip() or auth.DEFAULT_USER_SETTINGS["display_timezone"],
        n_simulations=n_simulations,
        openrouter_api_key=request.form.get("openrouter_api_key", "").strip(),
        onboarded=True,
    )
    flash("Welcome! Your settings have been saved — you can change these any time on the Settings page.", "success")
    return redirect(url_for("web.index"))


@web_bp.get("/admin/diagnostics")
@login_required
def admin_diagnostics():
    if not current_user.is_admin:
        return redirect(url_for("web.index"))
    engine = app_module.get_engine()
    scenario_id = _scenario_id()
    results = _results_for_scenario(scenario_id)
    groups = _groups_for_results(engine, results)

    # Per-group min/max points achievable by the third-place finisher, from the
    # same clinch logic that drives the "Best 3rd ✓" markers — surfaced so the
    # cross-group best-third reasoning is inspectable.
    third_ranges = {}
    if not _is_pre_draw(scenario_id) and results:
        from app import clinch as _clinch
        fixtures_by_group = results.get("fixtures", {})
        for g in groups:
            fixtures = fixtures_by_group.get(g["name"])
            if fixtures:
                third_ranges[g["name"]] = _clinch.group_third_place_range(g, fixtures)

    return render_template(
        "diagnostics.html",
        groups=groups,
        third_ranges=third_ranges,
        results=results,
        scenario_id=scenario_id,
    )


@web_bp.get("/admin/usage")
@login_required
def admin_usage():
    if not current_user.is_admin:
        return redirect(url_for("web.index"))
    import json, time as _time
    from collections import defaultdict, Counter

    path = data_store._PAGEVIEWS_PATH
    rows = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass

    now = _time.time()
    day = 86400

    def window(rows, seconds):
        cutoff = now - seconds
        return [r for r in rows if r.get("ts", 0) >= cutoff]

    def unique_ips(rows):
        return len({r["ip"] for r in rows if r.get("ip")})

    rows_24h = window(rows, day)
    rows_7d  = window(rows, 7 * day)

    # Page hit counts (last 7 days)
    page_counts = Counter(r.get("page", "?") for r in rows_7d)
    top_pages = page_counts.most_common(20)

    # Per-IP hit count (last 24h)
    ip_counts_24h = Counter(r.get("ip", "?") for r in rows_24h)
    top_ips = ip_counts_24h.most_common(20)

    # Hourly buckets for the last 7 days (for a simple chart)
    hours = 7 * 24
    buckets = [0] * hours
    cutoff_7d = now - 7 * day
    for r in rows:
        ts = r.get("ts", 0)
        if ts >= cutoff_7d:
            idx = int((ts - cutoff_7d) / 3600)
            if 0 <= idx < hours:
                buckets[idx] += 1

    # Unique IP counts per day for last 7 days
    daily_uniq = []
    for d in range(6, -1, -1):
        start = now - (d + 1) * day
        end   = now - d * day
        day_rows = [r for r in rows if start <= r.get("ts", 0) < end]
        import datetime
        label = datetime.datetime.utcfromtimestamp(end).strftime("%a %d %b")
        daily_uniq.append({"label": label, "hits": len(day_rows), "uniq": unique_ips(day_rows)})

    # Per-user hit count total
    user_counts = Counter(r.get("user") or "(anonymous)" for r in rows_7d)
    top_users = user_counts.most_common(20)

    return render_template(
        "admin_usage.html",
        total=len(rows),
        hits_24h=len(rows_24h),
        hits_7d=len(rows_7d),
        uniq_24h=unique_ips(rows_24h),
        uniq_7d=unique_ips(rows_7d),
        top_pages=top_pages,
        top_ips=top_ips,
        top_users=top_users,
        daily_uniq=daily_uniq,
        hourly_buckets=buckets,
    )


@web_bp.get("/settings")
def settings():
    engine = app_module.get_engine()
    all_team_names = sorted(t["name"] for t in engine.data["teams"])
    return render_template(
        "settings.html",
        settings=current_user.settings,
        global_settings=data_store.load_global_settings(),
        all_team_names=all_team_names,
        scenario_list=data_store.list_scenarios(_username()),
        admin_users=_admin_users_with_usage() if current_user.is_admin else None,
        admin_email_env=auth.ADMIN_EMAIL_ENV,
        admin_username_env=auth.ADMIN_USERNAME_ENV,
        invite_list=data_store.list_invites() if current_user.is_admin else None,
    )


@web_bp.post("/settings")
def settings_save():
    n_simulations = request.form.get("n_simulations", "").strip()
    try:
        n_simulations = max(100, min(int(n_simulations), 500_000))
    except ValueError:
        n_simulations = auth.DEFAULT_USER_SETTINGS["n_simulations"]

    openrouter_key_mode = request.form.get("openrouter_key_mode", "").strip()
    if openrouter_key_mode not in ("own", "shared"):
        openrouter_key_mode = auth.DEFAULT_USER_SETTINGS["openrouter_key_mode"]

    auth.update_settings(
        current_user.username,
        openrouter_api_key=request.form.get("openrouter_api_key", "").strip(),
        openrouter_key_mode=openrouter_key_mode,
        openrouter_model=request.form.get("openrouter_model", "").strip() or auth.DEFAULT_USER_SETTINGS["openrouter_model"],
        display_timezone=request.form.get("display_timezone", "").strip() or auth.DEFAULT_USER_SETTINGS["display_timezone"],
        n_simulations=n_simulations,
        default_team=request.form.get("default_team", "").strip() or auth.DEFAULT_USER_SETTINGS["default_team"],
        favorite_team=request.form.get("favorite_team", "").strip(),
        onboarded=True,
    )

    # The official-results API key and shared OpenRouter key are global
    # settings shared across all accounts, so only the admin may change them.
    if current_user.is_admin:
        global_updates = {}
        if "football_data_api_key" in request.form:
            global_updates["football_data_api_key"] = request.form.get("football_data_api_key", "").strip()
        if "shared_openrouter_api_key" in request.form:
            global_updates["shared_openrouter_api_key"] = request.form.get("shared_openrouter_api_key", "").strip()
        if "admin_email" in request.form:
            global_updates["admin_email"] = request.form.get("admin_email", "").strip()
        if "invite_only" in request.form:
            global_updates["invite_only"] = request.form.get("invite_only") == "1"
        try:
            if "shared_llm_daily_limit" in request.form:
                global_updates["shared_llm_daily_limit"] = max(1000, int(request.form["shared_llm_daily_limit"]))
            if "shared_llm_weekly_limit" in request.form:
                global_updates["shared_llm_weekly_limit"] = max(1000, int(request.form["shared_llm_weekly_limit"]))
        except (ValueError, TypeError):
            pass
        if global_updates:
            data_store.save_global_settings(global_updates)

    flash("Settings saved.", "success")
    return redirect(url_for("web.settings"))


@web_bp.post("/account/regenerate-api-slug")
def regenerate_api_slug():
    auth.regenerate_api_slug(current_user.username)
    flash("API slug regenerated. Update any scripts using the old one.", "success")
    return redirect(url_for("web.settings"))


@web_bp.post("/account/password")
def change_password():
    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    new_password_confirm = request.form.get("new_password_confirm") or ""

    if not current_user.check_password(current_password):
        flash("Current password is incorrect.", "danger")
        return redirect(url_for("web.settings"))

    error = auth.validate_password(new_password)
    if not error and new_password != new_password_confirm:
        error = "New passwords do not match."
    if error:
        flash(error, "danger")
        return redirect(url_for("web.settings"))

    auth.set_password(current_user.username, new_password)
    flash("Password updated.", "success")
    return redirect(url_for("web.settings"))


@web_bp.get("/admin/approve/<username>")
@login_required
def admin_approve_user(username):
    if not current_user.is_admin:
        flash("Only the admin can approve accounts.", "danger")
        return redirect(url_for("web.settings"))
    if auth.approve_user(username):
        flash(f"Account '{username}' approved — they can now log in.", "success")
    else:
        flash(f"Account '{username}' not found.", "danger")
    return redirect(url_for("web.settings"))


@web_bp.post("/admin/approve/<username>")
@login_required
def admin_approve_user_post(username):
    return admin_approve_user(username)


@web_bp.post("/admin/invites/new")
@login_required
def admin_invite_create():
    if not current_user.is_admin:
        flash("Only the admin can create invite links.", "danger")
        return redirect(url_for("web.settings"))
    label = request.form.get("label", "").strip() or "Invite"
    try:
        max_uses = max(1, int(request.form.get("max_uses", 1)))
    except (ValueError, TypeError):
        max_uses = 1
    data_store.create_invite(label, max_uses)
    flash(f"Invite link '{label}' created.", "success")
    return redirect(url_for("web.settings") + "#admin-invites")


@web_bp.post("/admin/invites/<token>/delete")
@login_required
def admin_invite_delete(token):
    if not current_user.is_admin:
        flash("Only the admin can delete invite links.", "danger")
        return redirect(url_for("web.settings"))
    data_store.delete_invite(token)
    flash("Invite link deleted.", "success")
    return redirect(url_for("web.settings") + "#admin-invites")
