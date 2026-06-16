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


def _scenario_id() -> str:
    return request.args.get("s") or (request.json.get("scenario") if request.is_json else None) or "current"


def _require_results():
    scenario_id = _scenario_id()
    results = app_module.get_or_run_results(g.user.username, scenario_id,
                                              n=g.user.settings.get("n_simulations"))
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
    scenario_id = _scenario_id()

    engine = app_module.get_engine()

    # Save the previous results as a snapshot before overwriting, so the new
    # run can be compared against it.
    previous = app_module.get_simulation_results(g.user.username, scenario_id)
    if previous is not None:
        data_store.save_snapshot(g.user.username, previous, label=save_label)

    scenario = data_store.load_scenario(scenario_id, g.user.username)
    if scenario is None:
        return jsonify({"error": "Unknown scenario"}), 404
    results = engine.run(n, actuals=scenario["actuals"])
    app_module.set_simulation_results(g.user.username, results, scenario_id)
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
    if not g.user.is_admin:
        return jsonify({"error": "Only the admin account can update results."}), 403
    engine = app_module.get_engine()

    # Per the scenarios feature: snapshot the real-world results as a frozen
    # scenario before they're overwritten, so users can keep exploring "what
    # the projections looked like before this update".
    archived = data_store.archive_current_scenario()

    sync_info = fetch_and_apply_official_results(engine)
    if "error" in sync_info:
        return jsonify(sync_info), 400
    sync_info["archived_scenario"] = {"id": archived["id"], "label": archived["label"]}

    default_n = g.user.settings.get("n_simulations", auth.DEFAULT_USER_SETTINGS["n_simulations"])
    n = request.json.get("n", default_n) if request.is_json else default_n
    n = max(100, min(int(n), 500_000))

    previous = app_module.get_simulation_results(g.user.username, "current")
    if previous is not None:
        data_store.save_snapshot(g.user.username, previous, label="Before results sync")

    actuals = data_store.load_actuals()
    results = engine.run(n, actuals=actuals)
    app_module.set_simulation_results(g.user.username, results, "current")

    # If the user previously entered results manually (because the official
    # results feed was slow/incorrect), compare that manual snapshot against
    # the freshly-synced official actuals.
    manual_comparison = {"status": "none"}
    manual = data_store.load_scenario(data_store.MANUAL_SCENARIO_ID)
    if manual is not None:
        if manual["actuals"].get("group_results") == actuals.get("group_results") and \
                manual["actuals"].get("knockout_results") == actuals.get("knockout_results"):
            data_store.delete_scenario(data_store.MANUAL_SCENARIO_ID)
            manual_comparison = {"status": "match"}
        else:
            manual_comparison = {"status": "mismatch"}
    sync_info["manual_comparison"] = manual_comparison

    return jsonify({
        "ok": True,
        "sync": sync_info,
        "n_simulations": results["n_simulations"],
        "elapsed_seconds": results["elapsed_seconds"],
    })


@api_bp.post("/scenarios/update")
def update_scenarios():
    """Rebuild the canonical set of auto-generated scenarios — one per unique
    state of the tournament (before the first match, then after each played
    match) — pruning any that no longer match the real results."""
    if not g.user.is_admin:
        return jsonify({"error": "Only the admin account can update scenarios."}), 403
    result = data_store.update_scenarios()
    return jsonify({"ok": True, **result})


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

    from app import data_store
    gs = data_store.load_global_settings()
    # Only enforce quota for shared-key users (own-key users pay their own bill).
    if g.user.settings.get("openrouter_key_mode") == "shared":
        quota_error = data_store.check_llm_quota(g.user.username, gs)
        if quota_error:
            return jsonify({"error": quota_error}), 429

    scenario_id = data.get("scenario") or _scenario_id()
    results = app_module.get_or_run_results(g.user.username, scenario_id,
                                              n=g.user.settings.get("n_simulations"))
    engine = app_module.get_engine()
    history = data.get("history") if isinstance(data.get("history"), list) else None
    answer, tokens_used = answer_question(data["question"], engine, results, user_settings=g.user.settings,
                                           history=history, global_settings=gs)
    if tokens_used > 0:
        data_store.record_llm_usage(g.user.username, tokens_used)

    usage = data_store.get_llm_usage(g.user.username)
    return jsonify({
        "question": data["question"],
        "answer": answer,
        "usage": {
            "daily_tokens": usage["daily_tokens"],
            "weekly_tokens": usage["weekly_tokens"],
            "daily_limit": int(gs.get("shared_llm_daily_limit") or data_store.LLM_DAILY_LIMIT),
            "weekly_limit": int(gs.get("shared_llm_weekly_limit") or data_store.LLM_WEEKLY_LIMIT),
        },
    })


# ----------------------------------------------------------------------
# Scenarios
# ----------------------------------------------------------------------

@api_bp.get("/scenarios")
def get_scenarios():
    """List scenarios, optionally filtered by quality flags, e.g.
    ?group_stage_complete=true&has_knockout_results=false"""
    scenarios = data_store.list_scenarios(g.user.username)
    quality_keys = ("group_stage_complete", "has_group_results",
                    "has_knockout_results", "knockout_complete")
    for key in quality_keys:
        if key in request.args:
            want = request.args.get(key).lower() in ("1", "true", "yes")
            scenarios = [s for s in scenarios if bool(s.get(key)) == want]
    return jsonify(scenarios)


# ----------------------------------------------------------------------
# Actual results (entered as the real tournament progresses)
# ----------------------------------------------------------------------

@api_bp.get("/actuals")
def get_actuals():
    scenario = data_store.load_scenario(_scenario_id(), g.user.username)
    if scenario is None:
        return jsonify({"error": "Unknown scenario"}), 404
    return jsonify(scenario["actuals"])


def _invalidate_results(scenario_id):
    """Drop any cached simulation results for this scenario, for every
    account, so the next page load/API call re-runs against the new
    actuals."""
    for key in list(app_module._simulation_results.keys()):
        if key[1] == scenario_id:
            del app_module._simulation_results[key]


def _load_actuals_for_edit():
    """Resolve the (scenario_id, actuals) pair to mutate for a results edit.

    - ``s=current`` (or no `s`/`scenario` param) edits ``data/actuals.json``
      directly — used for real-world result corrections.
    - ``s=<other>`` and ``fork=true`` forks that scenario into a new "what
      if" scenario and edits the copy, leaving the original untouched.
    - ``s=<other>`` without ``fork`` edits that scenario's saved actuals
      in place.
    """
    scenario_id = _scenario_id()
    fork = (request.args.get("fork") or (request.json or {}).get("fork") if request.is_json else request.args.get("fork"))
    fork = str(fork).lower() in ("1", "true", "yes") if fork else False

    scenario = data_store.load_scenario(scenario_id, g.user.username)
    if scenario is None:
        return None, None, False
    import copy
    actuals = copy.deepcopy(scenario["actuals"])
    if fork:
        return None, actuals, True  # caller forks after mutating
    if scenario_id == "current":
        return "current", actuals, False
    return scenario_id, actuals, False


@api_bp.post("/actuals/group_result")
def post_group_result():
    """
    Body: {"group": "A", "home": "Mexico", "away": "South Africa",
           "home_goals": 2, "away_goals": 1}

    Optional query params: ?s=<scenario_id> to edit a non-current scenario,
    ?fork=true to create a new "what if" scenario from the result instead of
    editing in place.
    """
    body = request.get_json()
    required = ("group", "home", "away", "home_goals", "away_goals")
    if not body or any(k not in body for k in required):
        return jsonify({"error": f"Missing fields, required: {required}"}), 400

    engine = app_module.get_engine()
    gname = body["group"].upper()
    if gname not in engine.group_pos:
        return jsonify({"error": "Unknown group"}), 404

    base_scenario_id = _scenario_id()
    target_id, actuals, do_fork = _load_actuals_for_edit()
    if actuals is None:
        return jsonify({"error": "Unknown scenario"}), 404

    matches = actuals["group_results"].setdefault(gname, [])
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

    return _save_edited_actuals(target_id, base_scenario_id, actuals, do_fork)


@api_bp.post("/actuals/knockout_result")
def post_knockout_result():
    """Body: {"match": 73, "winner": "Spain"}. Same `s`/`fork` params as
    /actuals/group_result."""
    body = request.get_json()
    if not body or "match" not in body or "winner" not in body:
        return jsonify({"error": "Missing fields, required: match, winner"}), 400

    engine = app_module.get_engine()
    if body["winner"] not in engine.team_idx:
        return jsonify({"error": "Unknown team"}), 404

    base_scenario_id = _scenario_id()
    target_id, actuals, do_fork = _load_actuals_for_edit()
    if actuals is None:
        return jsonify({"error": "Unknown scenario"}), 404

    actuals["knockout_results"][str(int(body["match"]))] = body["winner"]

    return _save_edited_actuals(target_id, base_scenario_id, actuals, do_fork)


def _save_edited_actuals(target_id, base_scenario_id, actuals, do_fork):
    if do_fork:
        scenario = data_store.fork_scenario(base_scenario_id, actuals, username=g.user.username)
        return jsonify({"ok": True, "scenario": {k: v for k, v in scenario.items() if k != "actuals"},
                         "actuals": actuals})
    if data_store._is_global_scenario_id(target_id) and not g.user.is_admin:
        return jsonify({"error": "Only the admin account can edit this scenario. Use fork=true to create your own copy."}), 403
    if target_id == "current":
        data_store.save_actuals(actuals)
        data_store.ensure_match_scenarios()
    else:
        existing = data_store.load_scenario(target_id, g.user.username)
        data_store.save_scenario(existing["label"], actuals, scenario_id=target_id, username=g.user.username)
    _invalidate_results(target_id)
    return jsonify({"ok": True, "scenario_id": target_id, "actuals": actuals})


@api_bp.post("/scenarios/hypothetical")
def create_hypothetical_scenario():
    """Create (replacing any existing) the single "what if" scenario by
    applying one group-result edit on top of the currently-active scenario's
    actuals, then run a simulation for it and make it the active scenario.

    Body: {"group": "A", "home": "Mexico", "away": "South Africa",
           "home_goals": 2, "away_goals": 1, "base": "current"}
    """
    from flask import session
    body = request.get_json() or {}
    required = ("group", "home", "away", "home_goals", "away_goals")
    if any(k not in body for k in required):
        return jsonify({"error": f"Missing fields, required: {required}"}), 400

    engine = app_module.get_engine()
    gname = body["group"].upper()
    if gname not in engine.group_pos:
        return jsonify({"error": "Unknown group"}), 404

    base_id = body.get("base") or _scenario_id()
    base = data_store.load_scenario(base_id, g.user.username)
    if base is None:
        return jsonify({"error": "Unknown scenario"}), 404

    import copy
    actuals = copy.deepcopy(base["actuals"])
    matches = actuals["group_results"].setdefault(gname, [])
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

    # Only one "what if" scenario at a time.
    data_store.delete_hypothetical_scenario(g.user.username)
    scenario_id = data_store.HYPOTHETICAL_SCENARIO_ID
    key = ((g.user.username or "_anon").lower(), scenario_id)
    app_module._simulation_results.pop(key, None)

    label = f"What if: {body['home']} {body['home_goals']}-{body['away_goals']} {body['away']}"
    featured_match = {"group": gname, "home": body["home"], "away": body["away"]}
    scenario = data_store.save_scenario(label, actuals, based_on=base_id,
                                         scenario_id=scenario_id, draw=base.get("draw"),
                                         is_hypothetical=True, featured_match=featured_match,
                                         username=g.user.username)

    n = g.user.settings.get("n_simulations", auth.DEFAULT_USER_SETTINGS["n_simulations"])
    results = app_module.get_or_run_results(g.user.username, scenario_id, n=n)

    session["scenario_id"] = scenario_id
    return jsonify({
        "ok": True,
        "scenario": {k: v for k, v in scenario.items() if k != "actuals"},
        "group_advance_prob": (results or {}).get("group_advance_prob", {}),
        "winner_prob": (results or {}).get("winner_prob", {}),
    })


@api_bp.post("/actuals/live_score")
def post_live_score():
    """Record a live (in-progress) scoreline for a group match.

    Body: {"group": "A", "home": "Mexico", "away": "South Africa",
           "home_goals": 2, "away_goals": 1}

    Optional ``"finished": true`` marks the match as final instead of
    in-progress (removes it from ``live_matches`` rather than adding it) —
    used by the "Finish match" action.

    Same `s`/`fork` query params as /actuals/group_result. Updates the
    group result with the given score AND marks the match as "in progress"
    in actuals["live_matches"], so it propagates into standings/brackets but
    is flagged as not-yet-final for display purposes."""
    body = request.get_json()
    required = ("group", "home", "away", "home_goals", "away_goals")
    if not body or any(k not in body for k in required):
        return jsonify({"error": f"Missing fields, required: {required}"}), 400

    engine = app_module.get_engine()
    gname = body["group"].upper()
    if gname not in engine.group_pos:
        return jsonify({"error": "Unknown group"}), 404

    base_scenario_id = _scenario_id()
    target_id, actuals, do_fork = _load_actuals_for_edit()
    if actuals is None:
        return jsonify({"error": "Unknown scenario"}), 404

    matches = actuals["group_results"].setdefault(gname, [])
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

    live_matches = actuals.setdefault("live_matches", [])
    live_matches = [
        lm for lm in live_matches
        if {lm.get("home"), lm.get("away")} != {body["home"], body["away"]}
    ]
    if not body.get("finished"):
        live_matches.append({"home": body["home"], "away": body["away"]})
    actuals["live_matches"] = live_matches

    return _save_edited_actuals(target_id, base_scenario_id, actuals, do_fork)


@api_bp.post("/actuals/manual_snapshot")
def save_manual_snapshot():
    """Remember the current real-world actuals as the "manually entered"
    baseline, used later by /results/sync to detect whether official results
    match what was entered by hand."""
    if not g.user.is_admin:
        return jsonify({"error": "Only the admin account can edit official results."}), 403
    scenario = data_store.save_manual_snapshot()
    return jsonify({"ok": True, "scenario": {k: v for k, v in scenario.items() if k != "actuals"}})


@api_bp.post("/actuals/reset")
def reset_actuals():
    scenario_id = _scenario_id()
    if data_store._is_global_scenario_id(scenario_id) and not g.user.is_admin:
        return jsonify({"error": "Only the admin account can edit this scenario."}), 403
    if scenario_id == "current":
        data_store.save_actuals(data_store._empty_actuals())
    else:
        existing = data_store.load_scenario(scenario_id, g.user.username)
        if existing is None:
            return jsonify({"error": "Unknown scenario"}), 404
        data_store.save_scenario(existing["label"], data_store._empty_actuals(), scenario_id=scenario_id, username=g.user.username)
    _invalidate_results(scenario_id)
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


# ----------------------------------------------------------------------
# Draw phase
# ----------------------------------------------------------------------

@api_bp.get("/draw/pots")
def draw_pots():
    from app.simulation.draw import load_draw_pots
    return jsonify(load_draw_pots())


@api_bp.post("/draw/simulate")
def draw_simulate():
    """Body (optional): {"fixed": {letter: [team_or_null, ...]}, "seed": int}.
    Returns one randomly-completed draw."""
    from app.simulation.draw import load_draw_pots, simulate_draw
    body = request.get_json(silent=True) or {}
    data = load_draw_pots()
    import random
    seed = body.get("seed")
    rng = random.Random(seed) if seed is not None else random.Random()
    draw = simulate_draw(data["pots"], data["confederations"], data["host_groups"],
                          data["rival_pairs"], fixed=body.get("fixed"), rng=rng)
    return jsonify({"draw": draw})


@api_bp.post("/draw/save")
def draw_save():
    """Body: {"label": str, "draw": {letter: [...]}, "based_on": scenario_id,
    "scenario": scenario_id (optional, to update an existing draw scenario)}."""
    from app.simulation.draw import is_draw_complete
    body = request.get_json(silent=True) or {}
    draw = body.get("draw")
    if not draw:
        return jsonify({"error": "Missing 'draw'"}), 400
    label = body.get("label") or ("Custom draw" if is_draw_complete(draw) else "Partial draw")
    based_on = body.get("based_on") or "current"
    base = data_store.load_scenario(based_on, g.user.username)
    actuals = (base or {}).get("actuals") or data_store._empty_actuals()
    scenario_id = body.get("scenario")
    if scenario_id:
        existing = data_store.load_scenario(scenario_id, g.user.username)
        if existing is None:
            return jsonify({"error": "Unknown scenario"}), 404
        scenario = data_store.save_scenario(existing["label"], existing["actuals"], scenario_id=scenario_id, draw=draw, username=g.user.username)
        _invalidate_results(scenario_id)
    else:
        import copy
        scenario = data_store.save_scenario(label, copy.deepcopy(actuals), based_on=based_on, draw=draw, username=g.user.username)
    return jsonify({"ok": True, "scenario": {k: v for k, v in scenario.items() if k != "actuals"}})


@api_bp.post("/draw/compare")
def draw_compare():
    """Compute (and cache) the actual-draw vs. pre-draw winner-probability
    comparison. This can be slow the first time (it marginalizes over many
    simulated draws), so the UI calls this on demand."""
    import app as app_module
    engine = app_module.get_engine()
    n = current_user.settings.get("n_simulations") if current_user.is_authenticated else None
    username = current_user.username if current_user.is_authenticated else None

    current_results = app_module.get_or_run_results(username, "current", n=n)
    pre_draw_results = app_module.get_or_run_results(username, "pre-draw", n=n)

    comparison = []
    if current_results and pre_draw_results:
        for t in engine.team_names:
            comparison.append({
                "team": t,
                "current_winner_prob": current_results["winner_prob"].get(t, 0),
                "pre_draw_winner_prob": pre_draw_results["winner_prob"].get(t, 0),
            })
        comparison.sort(key=lambda r: r["current_winner_prob"], reverse=True)
    return jsonify({"comparison": comparison})


@api_bp.get("/draw/opponent_stats")
def draw_opponent_stats():
    """Average groupmate probabilities over many random draws (optionally
    completing a partial ``fixed`` draw passed as JSON body)."""
    from app.simulation.draw import simulate_many_draws, opponent_stats
    body = request.get_json(silent=True) or {}
    n = max(10, min(int(request.args.get("n", 200)), 2000))
    draws = simulate_many_draws(n, fixed=body.get("fixed"))
    return jsonify(opponent_stats(draws))


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
