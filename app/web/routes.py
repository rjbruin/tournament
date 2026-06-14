from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash, session
from flask_login import current_user, login_required

import app as app_module
from app import auth, data_store
from app.web.view_helpers import normalize_group_match, normalize_bracket_match, compute_group_table, utc_sort_key as _utc_sort_key

web_bp = Blueprint("web", __name__)


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


def _group_table_before(g, raw_fixtures, live_match, teams_by_name, results):
    """Standings for group `g` as they were before `live_match` (a
    normalized match dict) was played."""
    import copy
    before_fixtures = []
    for m in raw_fixtures:
        if {m.get("home"), m.get("away")} == {live_match.get("home_team"), live_match.get("away_team")}:
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
        return "current"
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
                data_store.delete_hypothetical_scenario()
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


@web_bp.get("/")
def index():
    engine = app_module.get_engine()
    scenario_id = _scenario_id()
    results = _results_for_scenario(scenario_id)
    groups = _groups_for_results(engine, results)
    teams_by_name = {t["name"]: t for t in engine.data["teams"]}

    all_normalized = []
    for g in (groups if not _is_pre_draw(scenario_id) else []):
        raw_fixtures = (results or {}).get("fixtures", {}).get(g["name"], [])
        normalized = [normalize_group_match(m) for m in raw_fixtures]
        for m, raw in zip(normalized, raw_fixtures):
            m["_group"] = g["name"]
            m["_sort_key"] = _utc_sort_key(raw)
            all_normalized.append(m)

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
        active_scenario_data = data_store.load_scenario(scenario_id)
        fm = (active_scenario_data or {}).get("featured_match")
        if fm:
            match = next((m for m in all_normalized
                          if m.get("_group") == fm.get("group")
                          and {m.get("home_team"), m.get("away_team")} == {fm.get("home"), fm.get("away")}),
                         None)
            if match:
                featured_fixture = match

    featured_is_live = bool(featured_fixture) and _is_live(featured_fixture)

    featured_group_table = None
    featured_group_table_before = None
    if featured_fixture and featured_fixture.get("_group"):
        g = next((g for g in groups if g["name"] == featured_fixture["_group"]), None)
        if g:
            raw_fixtures = (results or {}).get("fixtures", {}).get(g["name"], [])
            featured_group_table = compute_group_table(g, raw_fixtures, teams_by_name, results)

            if featured_is_live:
                featured_group_table_before = _group_table_before(g, raw_fixtures, featured_fixture, teams_by_name, results)

    scenario_list = data_store.list_scenarios()
    active_scenario = data_store.load_scenario(scenario_id)
    last_updated_ts = data_store.actuals_last_updated()
    last_updated = None
    if last_updated_ts:
        import time as _time
        last_updated = _time.strftime("%Y-%m-%d %H:%M UTC", _time.gmtime(last_updated_ts))

    return render_template(
        "index.html",
        tournament=engine.data["tournament"],
        teams_by_name=teams_by_name,
        results=results,
        scenario_id=scenario_id,
        active_scenario=active_scenario,
        scenario_list=scenario_list,
        last_updated=last_updated,
        featured_fixture=featured_fixture,
        featured_is_live=featured_is_live,
        featured_group_table_before=featured_group_table_before,
        featured_group_table=featured_group_table,
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
    scenario = data_store.load_scenario(scenario_id) or data_store.load_scenario("current")
    try:
        team_form = compute_form(scenario["actuals"], engine)
    except Exception:
        team_form = {}

    base_order = sorted(engine.data["teams"], key=lambda t: -t["elo"])
    base_rank = {t["name"]: i + 1 for i, t in enumerate(base_order)}

    teams_sorted = sorted(
        engine.data["teams"],
        key=lambda t: -(t["elo"] + team_form.get(t["name"], 0)),
    )
    results = _results_for_scenario(scenario_id)
    for i, t in enumerate(teams_sorted, start=1):
        t["current_elo"] = t["elo"] + team_form.get(t["name"], 0)
        t["rank_change"] = base_rank[t["name"]] - i
        t["group_advance_prob"] = (results or {}).get("group_advance_prob", {}).get(t["name"])
        t["winner_prob"] = (results or {}).get("winner_prob", {}).get(t["name"])

    favorite_team = None
    if current_user.is_authenticated:
        favorite_team = current_user.settings.get("favorite_team") or None
    favorite = next((t for t in teams_sorted if t["name"] == favorite_team), None)

    return render_template(
        "teams.html",
        teams=teams_sorted,
        favorite=favorite,
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

    bracket_for_team = []
    if results and results.get("bracket_matches"):
        for mno, m in results["bracket_matches"].items():
            home = m.get("home", {})
            away = m.get("away", {})
            if home.get("team") == name or away.get("team") == name:
                bracket_for_team.append(normalize_bracket_match(m))
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

    _empty_odds = {"group_advance_prob": None, "winner_prob": None}

    def _odds_for_scenario(sid):
        if sid is None:
            return None
        r = app_module.get_or_run_results(_username(), sid, n=n)
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
        odds_history.append({"label": f"After {rname}", **(_odds_for_scenario(sid) or _empty_odds)})

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

    rounds = [
        ("Round of 32", [normalize_bracket_match(bm[m]) for m in order_r32]),
        ("Round of 16", [normalize_bracket_match(bm[m]) for m in order_r16]),
        ("Quarterfinals", [normalize_bracket_match(bm[m]) for m in order_qf]),
        ("Semifinals", [normalize_bracket_match(bm[m]) for m in order_sf]),
        ("Final", [normalize_bracket_match(bm[103])]),
    ]
    return render_template("bracket.html", results=results, rounds=rounds, scenario_id=scenario_id)


@web_bp.get("/fixtures")
def fixtures():
    engine = app_module.get_engine()
    scenario_id = _scenario_id()
    results = _results_for_scenario(scenario_id)
    groups = engine.groups
    all_fixtures = []
    if results is not None and not _is_pre_draw(scenario_id):
        fixtures_by_group = results.get("fixtures", {})
        for g in groups:
            raw_fixtures = fixtures_by_group.get(g["name"], [])
            for m in raw_fixtures:
                nm = normalize_group_match(m)
                nm["header"] = f"Group {g['name']}"
                nm["header_url"] = url_for("web.groups") + f"#group-{g['name']}"
                nm["sort_key"] = _utc_sort_key(m)
                all_fixtures.append(nm)
        bm = results.get("bracket_matches", {})
        for m in engine.all_knockout_defs:
            match = bm[m["match"]]
            nm = normalize_bracket_match(match)
            nm["header"] = nm["round"]
            nm["header_url"] = url_for("web.bracket") + f"#round-{nm['round'].replace(' ', '-')}"
            nm["sort_key"] = _utc_sort_key(match)
            all_fixtures.append(nm)
        all_fixtures.sort(key=lambda f: f["sort_key"])
    return render_template(
        "fixtures.html",
        groups=groups,
        all_fixtures=all_fixtures,
        results=results,
        scenario_id=scenario_id,
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
@login_required
def draw():
    from app.simulation.draw import load_draw_pots
    engine = app_module.get_engine()
    pots_data = load_draw_pots()

    actual_groups = {g["name"]: g["teams"] for g in engine.groups}

    n = current_user.settings.get("n_simulations")
    current_results = app_module.get_simulation_results(current_user.username, "current")
    pre_draw_results = app_module.get_simulation_results(current_user.username, "pre-draw")

    comparison = None
    if current_results and pre_draw_results:
        comparison = []
        for t in engine.team_names:
            comparison.append({
                "team": t,
                "current_winner_prob": current_results["winner_prob"].get(t, 0),
                "pre_draw_winner_prob": pre_draw_results["winner_prob"].get(t, 0),
            })
        comparison.sort(key=lambda r: r["current_winner_prob"], reverse=True)

    scenario_list = [s for s in data_store.list_scenarios() if s.get("draw") is not None or s["id"] == "current"]

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
    base = data_store.load_scenario(base_id)
    actuals = (base or {}).get("actuals") or data_store._empty_actuals()
    import copy
    scenario = data_store.fork_scenario(base_id, copy.deepcopy(actuals), label=label)
    flash(f"Created scenario '{scenario['label']}'.", "success")
    return redirect(url_for("web.index"))


@web_bp.post("/scenarios/<scenario_id>/delete")
@login_required
def scenarios_delete(scenario_id):
    if data_store.delete_scenario(scenario_id):
        flash("Scenario deleted.", "success")
    else:
        flash("Could not delete that scenario.", "danger")
    return redirect(url_for("web.index"))


@web_bp.get("/scenarios/compare")
@login_required
def scenario_compare():
    engine = app_module.get_engine()
    scenario_list = data_store.list_scenarios()
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
            "scenario": data_store.load_scenario(scenario_id),
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


@web_bp.get("/settings")
def settings():
    engine = app_module.get_engine()
    all_team_names = sorted(t["name"] for t in engine.data["teams"])
    return render_template(
        "settings.html",
        settings=current_user.settings,
        global_settings=data_store.load_global_settings(),
        all_team_names=all_team_names,
    )


@web_bp.post("/settings")
def settings_save():
    n_simulations = request.form.get("n_simulations", "").strip()
    try:
        n_simulations = max(100, min(int(n_simulations), 500_000))
    except ValueError:
        n_simulations = auth.DEFAULT_USER_SETTINGS["n_simulations"]

    auth.update_settings(
        current_user.username,
        openrouter_api_key=request.form.get("openrouter_api_key", "").strip(),
        openrouter_model=request.form.get("openrouter_model", "").strip() or auth.DEFAULT_USER_SETTINGS["openrouter_model"],
        display_timezone=request.form.get("display_timezone", "").strip() or auth.DEFAULT_USER_SETTINGS["display_timezone"],
        n_simulations=n_simulations,
        default_team=request.form.get("default_team", "").strip() or auth.DEFAULT_USER_SETTINGS["default_team"],
        favorite_team=request.form.get("favorite_team", "").strip(),
        onboarded=True,
    )

    # The official-results API key is a shared/global setting (it's not tied
    # to any one account), so only an authenticated user can change it but
    # it applies to everyone.
    if "football_data_api_key" in request.form:
        data_store.save_global_settings({
            "football_data_api_key": request.form.get("football_data_api_key", "").strip(),
        })

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


