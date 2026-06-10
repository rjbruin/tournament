from flask import Blueprint, jsonify, request, current_app, g
from flask_login import current_user

import app as app_module
from app import auth, data_store
from app.llm.interface import answer_question
from app.results_source import fetch_and_apply_official_results

api_bp = Blueprint("api", __name__)


@api_bp.before_request
def _authenticate():
    """Allow API access either via the normal session cookie (used by the
    web UI's own JS) or via a per-account API slug, so accounts can be used
    headlessly:

        curl -H "Authorization: Bearer <api_slug>" .../api/stats
        curl ".../api/stats?api_key=<api_slug>"
    """
    if request.endpoint == "api.health":
        return

    if current_user.is_authenticated:
        g.user = current_user._get_current_object()
        return

    slug = request.args.get("api_key", "")
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        slug = auth_header[len("Bearer "):].strip()

    user = auth.get_user_by_api_slug(slug) if slug else None
    if user is None:
        return jsonify({"error": "Unauthorized. Provide a session cookie or an API key "
                                  "(Authorization: Bearer <api_slug>, or ?api_key=<api_slug>)."}), 401
    g.user = user


def _require_results():
    results = app_module.get_simulation_results(g.user.username)
    if results is None:
        return None, (jsonify({"error": "No simulation results. Run /api/simulate first."}), 400)
    return results, None


@api_bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@api_bp.post("/simulate")
def simulate():
    default_n = g.user.settings.get("n_simulations", auth.DEFAULT_USER_SETTINGS["n_simulations"])
    n = request.json.get("n", default_n) if request.is_json else default_n
    n = max(100, min(int(n), 500_000))
    save_label = request.json.get("label") if request.is_json else None

    engine = app_module.get_engine()

    # Save the previous results as a snapshot before overwriting, so the new
    # run can be compared against it.
    previous = app_module.get_simulation_results(g.user.username)
    if previous is not None:
        data_store.save_snapshot(g.user.username, previous, label=save_label)

    actuals = data_store.load_actuals()
    results = engine.run(n, actuals=actuals)
    app_module.set_simulation_results(g.user.username, results)
    return jsonify({
        "ok": True,
        "n_simulations": results["n_simulations"],
        "elapsed_seconds": results["elapsed_seconds"],
    })


@api_bp.post("/results/sync")
def sync_results():
    """Fetch official World Cup results from football-data.org, merge any
    newly-completed group-stage matches into data/actuals.json, and re-run
    the simulation for the current account using those updated actuals."""
    engine = app_module.get_engine()
    sync_info = fetch_and_apply_official_results(engine)
    if "error" in sync_info:
        return jsonify(sync_info), 400

    default_n = g.user.settings.get("n_simulations", auth.DEFAULT_USER_SETTINGS["n_simulations"])
    n = request.json.get("n", default_n) if request.is_json else default_n
    n = max(100, min(int(n), 500_000))

    previous = app_module.get_simulation_results(g.user.username)
    if previous is not None:
        data_store.save_snapshot(g.user.username, previous, label="Before results sync")

    actuals = data_store.load_actuals()
    results = engine.run(n, actuals=actuals)
    app_module.set_simulation_results(g.user.username, results)

    return jsonify({
        "ok": True,
        "sync": sync_info,
        "n_simulations": results["n_simulations"],
        "elapsed_seconds": results["elapsed_seconds"],
    })


@api_bp.get("/stats")
def stats():
    results, err = _require_results()
    if err:
        return err
    return jsonify(results)


@api_bp.get("/winner_probabilities")
def winner_probabilities():
    results, err = _require_results()
    if err:
        return err
    data = sorted(
        results["winner_prob"].items(), key=lambda x: x[1], reverse=True
    )
    return jsonify([{"team": t, "probability": p} for t, p in data])


@api_bp.get("/finalist_probabilities")
def finalist_probabilities():
    results, err = _require_results()
    if err:
        return err
    data = sorted(
        results["finalist_prob"].items(), key=lambda x: x[1], reverse=True
    )
    return jsonify([{"team": t, "probability": p} for t, p in data])


@api_bp.get("/semifinal_probabilities")
def semifinal_probabilities():
    results, err = _require_results()
    if err:
        return err
    data = sorted(
        results["semifinal_prob"].items(), key=lambda x: x[1], reverse=True
    )
    return jsonify([{"team": t, "probability": p} for t, p in data])


@api_bp.get("/quarterfinal_probabilities")
def quarterfinal_probabilities():
    results, err = _require_results()
    if err:
        return err
    data = sorted(
        results["quarterfinal_prob"].items(), key=lambda x: x[1], reverse=True
    )
    return jsonify([{"team": t, "probability": p} for t, p in data])


@api_bp.get("/group_advance_probabilities")
def group_advance_probabilities():
    results, err = _require_results()
    if err:
        return err
    engine = app_module.get_engine()
    out = {}
    for g in engine.groups:
        out[g["name"]] = {
            t: results["group_advance_prob"].get(t, 0) for t in g["teams"]
        }
    return jsonify(out)


@api_bp.get("/group/<group_name>")
def group_detail(group_name: str):
    results, err = _require_results()
    if err:
        return err
    engine = app_module.get_engine()
    group = next((g for g in engine.groups if g["name"] == group_name.upper()), None)
    if group is None:
        return jsonify({"error": "Group not found"}), 404
    teams = []
    for tname in group["teams"]:
        tidx = engine.team_idx[tname]
        team_data = engine.data["teams"][tidx]
        teams.append({
            "name": tname,
            "elo": team_data["elo"],
            "confederation": team_data["confederation"],
            "advance_prob": results["group_advance_prob"].get(tname, 0),
            "r16_prob": results["round_of_16_prob"].get(tname, 0),
            "qf_prob": results["quarterfinal_prob"].get(tname, 0),
            "sf_prob": results["semifinal_prob"].get(tname, 0),
            "final_prob": results["finalist_prob"].get(tname, 0),
            "winner_prob": results["winner_prob"].get(tname, 0),
        })
    teams.sort(key=lambda t: t["winner_prob"], reverse=True)
    return jsonify({"group": group_name.upper(), "teams": teams})


@api_bp.get("/team/<team_name>")
def team_detail(team_name: str):
    results, err = _require_results()
    if err:
        return err
    engine = app_module.get_engine()
    if team_name not in engine.team_idx:
        return jsonify({"error": "Team not found"}), 404
    tidx = engine.team_idx[team_name]
    team_data = engine.data["teams"][tidx]
    group = next(g for g in engine.groups if team_name in g["teams"])
    return jsonify({
        "name": team_name,
        "elo": team_data["elo"],
        "confederation": team_data["confederation"],
        "group": group["name"],
        "group_advance_prob": results["group_advance_prob"].get(team_name, 0),
        "round_of_16_prob": results["round_of_16_prob"].get(team_name, 0),
        "quarterfinal_prob": results["quarterfinal_prob"].get(team_name, 0),
        "semifinal_prob": results["semifinal_prob"].get(team_name, 0),
        "finalist_prob": results["finalist_prob"].get(team_name, 0),
        "winner_prob": results["winner_prob"].get(team_name, 0),
    })


@api_bp.post("/query")
def query():
    data = request.get_json()
    if not data or "question" not in data:
        return jsonify({"error": "Missing 'question' field"}), 400
    results = app_module.get_simulation_results(g.user.username)
    engine = app_module.get_engine()
    history = data.get("history") if isinstance(data.get("history"), list) else None
    answer = answer_question(data["question"], engine, results, user_settings=g.user.settings, history=history)
    return jsonify({"question": data["question"], "answer": answer})


# ----------------------------------------------------------------------
# Actual results (entered as the real tournament progresses)
# ----------------------------------------------------------------------

@api_bp.get("/actuals")
def get_actuals():
    return jsonify(data_store.load_actuals())


@api_bp.post("/actuals/group_result")
def post_group_result():
    """
    Body: {"group": "A", "home": "Mexico", "away": "South Africa",
           "home_goals": 2, "away_goals": 1}
    """
    body = request.get_json()
    required = ("group", "home", "away", "home_goals", "away_goals")
    if not body or any(k not in body for k in required):
        return jsonify({"error": f"Missing fields, required: {required}"}), 400

    engine = app_module.get_engine()
    gname = body["group"].upper()
    if gname not in engine.group_pos:
        return jsonify({"error": "Unknown group"}), 404

    actuals = data_store.load_actuals()
    matches = actuals["group_results"].setdefault(gname, [])
    # Replace any existing entry for the same fixture
    matches = [
        m for m in matches
        if {m.get("home"), m.get("away")} != {body["home"], body["away"]}
    ]
    matches.append({
        "home": body["home"],
        "away": body["away"],
        "home_goals": int(body["home_goals"]),
        "away_goals": int(body["away_goals"]),
    })
    actuals["group_results"][gname] = matches
    data_store.save_actuals(actuals)
    return jsonify({"ok": True, "actuals": actuals})


@api_bp.post("/actuals/knockout_result")
def post_knockout_result():
    """Body: {"match": 73, "winner": "Spain"}"""
    body = request.get_json()
    if not body or "match" not in body or "winner" not in body:
        return jsonify({"error": "Missing fields, required: match, winner"}), 400

    engine = app_module.get_engine()
    if body["winner"] not in engine.team_idx:
        return jsonify({"error": "Unknown team"}), 404

    actuals = data_store.load_actuals()
    actuals["knockout_results"][str(int(body["match"]))] = body["winner"]
    data_store.save_actuals(actuals)
    return jsonify({"ok": True, "actuals": actuals})


@api_bp.post("/actuals/reset")
def reset_actuals():
    data_store.save_actuals(data_store._empty_actuals())
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# Snapshots / comparison
# ----------------------------------------------------------------------

@api_bp.get("/snapshots")
def list_snapshots():
    return jsonify(data_store.load_snapshots(g.user.username))


@api_bp.delete("/snapshots/<int:index>")
def delete_snapshot(index: int):
    if not data_store.delete_snapshot(g.user.username, index):
        return jsonify({"error": "Snapshot not found"}), 404
    return jsonify({"ok": True})


@api_bp.get("/compare")
def compare():
    """Compare the current results against the most recently saved snapshot."""
    results, err = _require_results()
    if err:
        return err
    previous = data_store.get_previous_snapshot(g.user.username)
    if previous is None:
        return jsonify({"error": "No previous snapshot to compare against."}), 404

    deltas = {}
    for key in ("group_advance_prob", "round_of_16_prob", "quarterfinal_prob",
                "semifinal_prob", "finalist_prob", "winner_prob"):
        deltas[key] = {
            team: round(results[key].get(team, 0) - previous.get(key, {}).get(team, 0), 4)
            for team in results[key]
        }
    return jsonify({"previous": previous, "deltas": deltas})
