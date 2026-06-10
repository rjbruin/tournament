from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash
from flask_login import current_user, login_required

import app as app_module
from app import auth, data_store
from app.web.view_helpers import normalize_group_match, normalize_bracket_match, compute_group_table, utc_sort_key as _utc_sort_key

web_bp = Blueprint("web", __name__)


@web_bp.get("/")
def index():
    engine = app_module.get_engine()
    results = app_module.get_simulation_results(current_user.username)
    groups = engine.groups
    groups_by_name = {g["name"]: g for g in engine.groups}
    teams_by_name = {t["name"]: t for t in engine.data["teams"]}

    group_tables = {}
    group_fixtures = {}
    for g in groups:
        raw_fixtures = (results or {}).get("fixtures", {}).get(g["name"], [])
        group_tables[g["name"]] = compute_group_table(g, raw_fixtures, teams_by_name, results)
        group_fixtures[g["name"]] = [normalize_group_match(m) for m in raw_fixtures]

    return render_template(
        "index.html",
        tournament=engine.data["tournament"],
        groups=groups,
        groups_by_name=groups_by_name,
        teams_by_name=teams_by_name,
        group_tables=group_tables,
        group_fixtures=group_fixtures,
        results=results,
    )


@web_bp.get("/group/<name>")
def group(name: str):
    engine = app_module.get_engine()
    results = app_module.get_simulation_results(current_user.username)
    group = next((g for g in engine.groups if g["name"] == name.upper()), None)
    if group is None:
        return redirect(url_for("web.index"))
    teams_by_name = {t["name"]: t for t in engine.data["teams"]}
    return render_template(
        "group.html",
        group=group,
        teams_by_name=teams_by_name,
        results=results,
    )


@web_bp.get("/team")
def team_default():
    return redirect(url_for("web.team", name="Netherlands"))


@web_bp.get("/team/<name>")
def team(name: str):
    engine = app_module.get_engine()
    results = app_module.get_simulation_results(current_user.username)
    teams_by_name = {t["name"]: t for t in engine.data["teams"]}
    if name not in teams_by_name:
        return redirect(url_for("web.team", name="Netherlands"))

    team_group = next((g for g in engine.groups if name in g["teams"]), None)

    fixtures_for_team = []
    if results and results.get("fixtures") and team_group:
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

    return render_template(
        "team.html",
        team=teams_by_name[name],
        team_group=team_group,
        all_team_names=all_team_names,
        fixtures_for_team=fixtures_for_team,
        bracket_for_team=bracket_for_team,
        results=results,
    )


@web_bp.get("/bracket")
def bracket():
    engine = app_module.get_engine()
    results = app_module.get_simulation_results(current_user.username)
    if results is None or "bracket_matches" not in results:
        return render_template("bracket.html", results=results, rounds=None)

    bm = results["bracket_matches"]
    rounds = [
        ("Round of 32", [normalize_bracket_match(bm[m]) for m in range(73, 89)]),
        ("Round of 16", [normalize_bracket_match(bm[m]) for m in range(89, 97)]),
        ("Quarterfinals", [normalize_bracket_match(bm[m]) for m in range(97, 101)]),
        ("Semifinals", [normalize_bracket_match(bm[m]) for m in (101, 102)]),
        ("Final", [normalize_bracket_match(bm[103])]),
    ]
    return render_template("bracket.html", results=results, rounds=rounds)


@web_bp.get("/fixtures")
def fixtures():
    engine = app_module.get_engine()
    results = app_module.get_simulation_results(current_user.username)
    groups = engine.groups
    all_fixtures = []
    if results is not None:
        fixtures_by_group = results.get("fixtures", {})
        for g in groups:
            for m in fixtures_by_group.get(g["name"], []):
                nm = normalize_group_match(m)
                nm["header"] = f"Group {g['name']}"
                nm["header_url"] = url_for("web.index") + f"#group-{g['name']}"
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
    )


@web_bp.get("/simulation-logic")
def simulation_logic():
    return render_template("simulation_logic.html")


@web_bp.get("/chat")
def chat():
    results = app_module.get_simulation_results(current_user.username)
    return render_template("chat.html", results=results)


@web_bp.get("/settings")
def settings():
    return render_template(
        "settings.html",
        settings=current_user.settings,
        global_settings=data_store.load_global_settings(),
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
