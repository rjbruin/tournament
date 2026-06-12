from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash
from flask_login import current_user, login_required

import app as app_module
from app import auth, data_store
from app.web.view_helpers import normalize_group_match, normalize_bracket_match, compute_group_table, utc_sort_key as _utc_sort_key

web_bp = Blueprint("web", __name__)


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
        if s != session.get("scenario_id"):
            # Switching to a different scenario: drop any cached results for
            # it so they're recomputed fresh (e.g. against the latest
            # data/actuals.json for "current") rather than showing whatever
            # was last computed for it, possibly under stale data.
            key = ((_username() or "_anon").lower(), s)
            app_module._simulation_results.pop(key, None)
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

    # The "current/next fixture" card: prefer a fixture without a result yet
    # (i.e. upcoming or in progress), otherwise fall back to the most
    # recently played one.
    featured_fixture = None
    if all_normalized:
        all_normalized.sort(key=lambda m: m["_sort_key"])
        upcoming = [m for m in all_normalized if not m.get("played")]
        featured_fixture = upcoming[0] if upcoming else all_normalized[-1]

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

    # Winner-probability progression across scenarios (pre-draw -> ... -> current),
    # using only already-computed (cached) results to keep the page fast.
    scenario_list = data_store.list_scenarios()
    ordered = [s for s in scenario_list if s.get("is_pre_draw")]
    others = [s for s in scenario_list if not s.get("is_pre_draw") and not s.get("is_current")]
    others.sort(key=lambda s: s.get("created_at") or 0)
    ordered += others
    ordered += [s for s in scenario_list if s.get("is_current")]

    winner_prob_history = []
    for s in ordered:
        r = app_module.get_simulation_results(_username(), s["id"])
        if r is None:
            continue
        winner_prob_history.append({
            "label": s["label"],
            "winner_prob": r.get("winner_prob", {}).get(name, 0),
        })

    return render_template(
        "team.html",
        team=teams_by_name[name],
        team_group=team_group,
        all_team_names=all_team_names,
        fixtures_for_team=fixtures_for_team,
        bracket_for_team=bracket_for_team,
        results=results,
        scenario_id=scenario_id,
        winner_prob_history=winner_prob_history,
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
            for m in fixtures_by_group.get(g["name"], []):
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


@web_bp.get("/simulations")
def simulations():
    results = app_module.get_simulation_results(current_user.username)
    snapshots = list(enumerate(data_store.load_snapshots(current_user.username)))
    snapshots.reverse()  # most recent first
    return render_template("simulations.html", results=results, snapshots=snapshots)


@web_bp.get("/simulations/<int:index>")
def simulation_detail(index: int):
    engine = app_module.get_engine()
    snapshot = data_store.get_snapshot(current_user.username, index)
    if snapshot is None:
        return redirect(url_for("web.simulations"))
    return render_template("simulation_detail.html", snapshot=snapshot, index=index, engine=engine)
