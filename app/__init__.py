import os
import secrets

from flask import Flask, abort, g, redirect, request, session, url_for
from flask_login import LoginManager, current_user

from app import auth
from app.simulation.engine import SimulationEngine
from app.tournaments import TournamentRegistry, load_registry
from app.flags import flag_emoji, flag_emoji_ioc, flag_url

# Per-account in-memory simulation results: {(username, tournament_id,
# scenario_id): results_dict}. Snapshots are persisted to disk (see
# data_store), but the "current" results only live in memory and are lost
# on restart — the user can re-run the simulation from their last
# snapshot's settings.
_simulation_results: dict[tuple, dict] = {}
_registry: TournamentRegistry = None

# Live-results state shared between the background poller and the status API.
# _live_version increments each time the poller writes new data AND the
# corresponding re-simulation completes. _live_processing is True while the
# simulation is running (so callers know to wait). _live_any_live mirrors
# whether any match is currently in play.
_live_version: int = 0
_live_processing: bool = False
_live_any_live: bool = False


def get_live_status() -> dict:
    return {
        "version": _live_version,
        "processing": _live_processing,
        "any_live": _live_any_live,
    }


def get_registry() -> TournamentRegistry:
    return _registry


def default_tournament_id() -> str:
    """The tournament to operate on when no explicit tournament_id is given.

    Inside a request, this is the tournament resolved from the URL/session
    by the app-level before_request hook (flask.g.tournament); outside a
    request (tests, background threads using a bare app_context, scripts)
    it falls back to the registry's first configured tournament — today the
    only one, so every pre-Stage-2 call site keeps behaving identically."""
    from flask import g, has_app_context
    if has_app_context():
        inst = getattr(g, "tournament", None)
        if inst is not None:
            return inst.id
    return _registry.default_id()


def get_engine(tournament_id: str = None) -> SimulationEngine:
    """Returns the engine for `tournament_id` (default: the registry's
    default tournament — today the only one, world-cup-2026/wc2026). Every
    existing zero-argument call site keeps working unchanged."""
    tid = tournament_id or default_tournament_id()
    inst = _registry.get_by_id(tid)
    if inst is None:
        raise ValueError(f"unknown tournament id {tid!r}")
    return inst.engine


def _cache_key(username: str, scenario_id: str = "current", tournament_id: str = None) -> tuple:
    tid = tournament_id or default_tournament_id()
    return ((username or "_anon").lower(), tid, scenario_id or "current")


def get_simulation_results(username: str, scenario_id: str = "current", tournament_id: str = None):
    return _simulation_results.get(_cache_key(username, scenario_id, tournament_id))


def set_simulation_results(
    username: str, results, scenario_id: str = "current", tournament_id: str = None
) -> None:
    _simulation_results[_cache_key(username, scenario_id, tournament_id)] = results


def forget_results(username: str, scenario_id: str, tournament_id: str = None) -> None:
    """Drop one cached results entry, e.g. when a user switches away from a
    scenario that should recompute fresh next time it's viewed. Callers
    used to reach into `_simulation_results` directly to do this — go
    through here instead so the cache-key shape stays encapsulated."""
    _simulation_results.pop(_cache_key(username, scenario_id, tournament_id), None)


def invalidate_results(scenario_id: str = "current", tournament_id: str = None) -> None:
    """Drop cached simulation results for `scenario_id` (in `tournament_id`,
    default the default tournament) across all accounts, so the next page
    load/API call re-runs against the freshly-updated actuals. Used by the
    live poller when a live score changes the real results."""
    tid = tournament_id or default_tournament_id()
    for key in list(_simulation_results.keys()):
        if key[1] == tid and key[2] == scenario_id:
            _simulation_results.pop(key, None)


# Number of independent draws to marginalize over for "pre-draw"/partial-draw
# scenarios, and the number of tournament simulations run per draw.
N_DRAWS = 12


_PROB_KEYS = [
    "group_advance_prob",
    "round_of_16_prob",
    "quarterfinal_prob",
    "semifinal_prob",
    "finalist_prob",
    "winner_prob",
]


def _average_results(per_draw_results: list[dict]) -> dict:
    """Average the per-team probability dicts across several `engine.run()`
    results (one per simulated draw), producing a single results dict
    suitable for caching. Non-probability keys (fixtures, bracket_matches,
    ...) are taken from the last draw as a representative example."""
    total_n = sum(r["n_simulations"] for r in per_draw_results)
    total_elapsed = sum(r["elapsed_seconds"] for r in per_draw_results)
    out = dict(per_draw_results[-1])
    for key in _PROB_KEYS:
        teams = set()
        for r in per_draw_results:
            teams.update(r.get(key, {}).keys())
        out[key] = {
            t: round(sum(r.get(key, {}).get(t, 0) for r in per_draw_results) / len(per_draw_results), 4)
            for t in teams
        }
    out["n_simulations"] = total_n
    out["elapsed_seconds"] = round(total_elapsed, 3)
    out["n_draws"] = len(per_draw_results)
    return out


_POLLER_USER = "_system"


def get_or_run_results(
    username: str, scenario_id: str = "current", n: int = None, tournament_id: str = None
):
    """Return cached simulation results for (account, tournament, scenario),
    running and caching a fresh simulation against that scenario's actuals
    if needed.

    For the "current" scenario with default N, the background poller pre-warms
    a shared cache entry under _POLLER_USER. Users without a custom N setting
    fall through to that entry, avoiding a redundant re-simulation."""
    scenario_id = scenario_id or "current"
    tid = tournament_id or default_tournament_id()
    cached = get_simulation_results(username, scenario_id, tid)
    if cached is not None:
        return cached
    # Fall back to the poller's pre-warmed result when no custom N is set.
    if scenario_id == "current" and n is None and username != _POLLER_USER:
        cached = get_simulation_results(_POLLER_USER, "current", tid)
        if cached is not None:
            return cached
    # Fall back to the checkpoint warmer's pre-warmed result for historical scenarios.
    if username != _POLLER_USER:
        cached = get_simulation_results(_POLLER_USER, scenario_id, tid)
        if cached is not None:
            return cached
    from app import data_store
    from app.simulation.draw import simulate_many_draws, is_draw_complete

    scenario = data_store.load_scenario(scenario_id, username)
    if scenario is None:
        return None

    n = n or 250_000
    draw = scenario.get("draw")
    engine = get_engine(tid)

    if scenario.get("is_pre_draw") or (draw is not None and not is_draw_complete(draw)):
        # Marginalize over many possible draws (fully random for "pre-draw",
        # or completing the fixed/partial draw for a partial-draw scenario).
        n_per_draw = max(100, n // N_DRAWS)
        draws = simulate_many_draws(N_DRAWS, fixed=draw)
        per_draw_results = [engine.run(n_per_draw, actuals=scenario["actuals"], groups=d) for d in draws]
        results = _average_results(per_draw_results)
    elif draw is not None:
        # Fully completed custom draw.
        results = engine.run(n, actuals=scenario["actuals"], groups=draw)
    else:
        results = engine.run(n, actuals=scenario["actuals"])

    set_simulation_results(username, results, scenario_id, tid)
    return results


class PrefixMiddleware:
    """WSGI middleware that lets the app be served under a URL prefix, e.g.

        REVERSE_PROXY <IP>:<port>/tournament/...  ->  app:5001/...

    Setting ``SCRIPT_NAME`` makes Flask's ``url_for`` (and therefore all
    templates, redirects, and static asset links) generate URLs that include
    the prefix, without any route having to know about it.
    """

    def __init__(self, app, prefix):
        self.app = app
        self.prefix = "/" + prefix.strip("/") if prefix else ""

    def __call__(self, environ, start_response):
        if not self.prefix:
            return self.app(environ, start_response)

        path = environ.get("PATH_INFO", "")
        if path.startswith(self.prefix):
            environ["SCRIPT_NAME"] = self.prefix
            environ["PATH_INFO"] = path[len(self.prefix):] or "/"
        return self.app(environ, start_response)


def create_app():
    global _registry

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")
    if app.secret_key == "dev-secret-key" and not app.debug:
        import warnings
        warnings.warn(
            "Using the default SECRET_KEY in a non-debug run. Set the "
            "SECRET_KEY environment variable to a random secret value "
            "before exposing this app publicly.",
            stacklevel=2,
        )

    # Cookies should only be sent over HTTPS in production. When developing
    # locally over plain HTTP, allow non-secure cookies via FLASK_DEBUG.
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "1") not in ("0", "false", "False")

    url_prefix = os.environ.get("URL_PREFIX", "").strip()
    if url_prefix:
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, url_prefix)

    from app.migrations import run_pending_migrations
    run_pending_migrations()

    _registry = load_registry()

    # Rebuild the canonical set of auto-generated scenarios (one per unique
    # state of the tournament). Cheap when already up to date; also what
    # repopulates the set right after the one-time scenario purge migration.
    try:
        from app import data_store
        data_store.update_scenarios()
    except Exception:
        pass

    from app.web.routes import account_bp, legacy_bp, picker_bp, web_bp
    from app.web.auth_routes import auth_bp
    from app.api.routes import api_bp

    app.register_blueprint(web_bp, url_prefix="/t/<slug>")
    app.register_blueprint(account_bp)
    app.register_blueprint(legacy_bp)
    app.register_blueprint(picker_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    login_manager = LoginManager()
    login_manager.login_view = "auth.login_get"
    login_manager.login_message_category = "info"
    # Harden the "remember me" cookie to match the session cookie settings.
    login_manager.remember_cookie_httponly = True
    login_manager.remember_cookie_samesite = "Lax"
    login_manager.remember_cookie_secure = app.config["SESSION_COOKIE_SECURE"]

    @login_manager.user_loader
    def load_user(user_id):
        return auth.get_user(user_id)

    login_manager.init_app(app)

    @app.before_request
    def resolve_tournament():
        # Runs before every request (any blueprint) so g.tournament /
        # g.tournament_slug are always available — including from
        # account-scoped pages (settings, changelog) that need to build a
        # `url_for('web.X')` link back into a tournament, and from
        # background threads that never go through a request at all (see
        # app.default_tournament_id's has_app_context guard). The active
        # tournament is "sticky" via the session, set authoritatively by
        # web_bp's url_value_preprocessor whenever a /t/<slug>/... URL is
        # visited (see app/web/routes.py).
        registry = get_registry()
        slug = session.get("tournament_slug") or registry.default_slug()
        inst = registry.get(slug) or registry.get(registry.default_slug())
        g.tournament = inst
        g.tournament_slug = inst.slug if inst else None
        g.all_tournaments = registry.list()

    @app.before_request
    def require_login():
        # Allow unauthenticated access only to the auth pages, static
        # assets, and legacy-URL redirects (which just forward to a public
        # or private page — the target enforces its own auth). Everything
        # else (including the API, which uses its own session-or-api-slug
        # check) requires a logged-in account.
        if request.endpoint is None:
            return
        if request.endpoint == "static" or request.endpoint.startswith("auth."):
            return
        if request.blueprint in ("api", "legacy", "picker"):
            return
        # The default "current" scenario (real tournament state) is public
        # so the app is useful while watching a game without an account.
        public_endpoints = {
            "web.index", "web.groups", "web.group", "web.team", "web.team_default",
            "web.bracket", "web.fixtures", "web.match_detail", "web.teams", "web.draw",
            "web.players", "web.matches",
            "account.manifest", "account.changelog", "account.simulation_logic",
        }
        if request.endpoint in public_endpoints:
            return
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login_get", next=request.full_path))

    @app.before_request
    def csrf_protect():
        # Simple session-bound CSRF token check for HTML form posts. The
        # JSON API (used via fetch with Content-Type: application/json, or
        # with an api_slug bearer token) is exempt — those requests can't be
        # triggered by a plain cross-site HTML form.
        if request.method == "POST" and request.blueprint != "api":
            token = session.get("_csrf_token")
            if not token or not secrets.compare_digest(token, request.form.get("_csrf_token", "")):
                abort(400, description="Invalid or missing CSRF token. Please refresh the page and try again.")

    @app.context_processor
    def inject_csrf_token():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_hex(16)
            session["_csrf_token"] = token
        return {"csrf_token": token}

    _maybe_start_live_poller(app)

    app.jinja_env.filters["flag"] = flag_emoji
    app.jinja_env.filters["flag_url"] = flag_url
    app.jinja_env.filters["flag_ioc"] = flag_emoji_ioc

    @app.template_filter("pct")
    def pct_filter(value, decimals=1):
        """Format a probability (0-1) as a percentage. Sampled values of exactly
        100% / 0% are statistical, not mathematical, certainties, so they render
        as ">99.9%" / "<0.1%" rather than a ✓/✗. Genuine mathematical clinch /
        elimination is communicated only through the clinch-aware badges.

        Thresholds are decimal-aware so the formatted string never rounds to
        "100%" or "0%" (which would imply false certainty)."""
        if value is None:
            return "—"
        # The rounding boundary where the formatted string would show 100% / 0%.
        # For decimals=0: 0.995 rounds to 100; for decimals=1: 0.9995 rounds to 100.0.
        half_ulp = 0.5 * (10 ** -(decimals + 2))
        if value >= 1.0 - half_ulp:
            return ">99%" if decimals == 0 else ">99.9%"
        if value <= half_ulp:
            return "<1%" if decimals == 0 else "<0.1%"
        return f"{value * 100:.{decimals}f}%"

    @app.template_filter("timestamp_to_date")
    def timestamp_to_date(value, fmt="%Y-%m-%d"):
        from datetime import datetime
        if not value:
            return "—"
        return datetime.fromtimestamp(value).strftime(fmt)

    @app.template_filter("local_time")
    def local_time(match, settings_tz=None, fmt="%a %d %b, %H:%M"):
        """Convert a fixture's local kickoff (date + local_time +
        local_timezone, e.g. venue's local time) to the configured display
        timezone."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        if not match or not match.get("date") or not match.get("local_time"):
            return ""
        venue_tz = match.get("local_timezone") or "UTC"
        tz_name = settings_tz
        if not tz_name and current_user.is_authenticated:
            tz_name = current_user.settings.get("display_timezone", "UTC")
        # Unauthenticated visitors default to Amsterdam local time (most of the
        # audience), rather than UTC.
        if not tz_name and not current_user.is_authenticated:
            tz_name = "Europe/Amsterdam"
        tz_name = tz_name or "UTC"
        try:
            dt = datetime.fromisoformat(f"{match['date']}T{match['local_time']}")
            dt = dt.replace(tzinfo=ZoneInfo(venue_tz))
            dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            return f"{match['date']} {match['local_time']}"
        return dt.strftime(fmt)

    @app.template_filter("kickoff_utc_ms")
    def kickoff_utc_ms(match):
        """Return the fixture's kickoff as milliseconds since epoch (for JS),
        or None if the kickoff time is unknown."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        if not match or not match.get("date") or not match.get("local_time"):
            return None
        try:
            dt = datetime.fromisoformat(f"{match['date']}T{match['local_time']}")
            dt = dt.replace(tzinfo=ZoneInfo(match.get("local_timezone") or "UTC"))
            return int(dt.timestamp() * 1000)
        except Exception:
            return None

    @app.context_processor
    def inject_settings():
        if current_user.is_authenticated:
            return {"app_settings": current_user.settings, "current_user": current_user}
        return {"app_settings": auth.DEFAULT_USER_SETTINGS, "current_user": current_user}

    @app.context_processor
    def inject_retro_available():
        from app.retrospective import load_retrospective
        return {"retro_available": load_retrospective() is not None}

    @app.context_processor
    def inject_form():
        # Team "form" badges (Elo modifier vs. expected results), computed
        # for the scenario currently being viewed (defaults to "current").
        from app import data_store
        from app.form import compute_form
        if request.blueprint == "api" or request.endpoint in (None, "static") or (request.endpoint or "").startswith("auth."):
            return {}
        # This whole function assumes a football-shaped engine
        # (data_store.load_scenario's global actuals.json, engine.groups,
        # engine.data["teams"]) — a groups-less bracket tournament
        # (Wimbledon) has none of that. base.html only ever reads
        # `active_scenario` unconditionally, so None is a safe default for
        # everything else here.
        tournament = getattr(g, "tournament", None)
        if tournament is not None and tournament.template != "fifa_world_cup":
            return {"team_form": {}, "active_scenario": None, "team_elos": {},
                    "team_clinch": {}, "live_teams": set()}
        scenario_id = request.args.get("s") or session.get("scenario_id") or "current"
        username = current_user.username if current_user.is_authenticated else None
        scenario = data_store.load_scenario(scenario_id, username) or data_store.load_scenario("current")
        engine = get_engine()
        try:
            team_form = compute_form(scenario["actuals"], engine)
        except Exception:
            team_form = {}
        team_elos = {t["name"]: t["elo"] for t in engine.data["teams"]} if engine else {}

        # Theoretical (sampling-free) qualification status per team for the
        # scenario being viewed, so badges everywhere can show a true "Q ✓"
        # only when advancement is mathematically guaranteed.
        team_clinch = {}
        try:
            from app import clinch as _clinch
            _results = get_or_run_results(username, scenario_id)
            if _results:
                team_clinch = _clinch.clinch_by_team(_results, engine.groups)
        except Exception:
            team_clinch = {}

        # Teams currently playing a live match — used to show the live-dot
        # indicator next to team names on standings, bracket, and team pages.
        live_teams: set = set()
        try:
            _actuals = data_store.load_actuals()
            for _lm in _actuals.get("live_matches", []):
                if _lm.get("home"):
                    live_teams.add(_lm["home"])
                if _lm.get("away"):
                    live_teams.add(_lm["away"])
        except Exception:
            pass

        return {"team_form": team_form, "active_scenario": scenario,
                "team_elos": team_elos, "team_clinch": team_clinch,
                "live_teams": live_teams}

    return app


# ----------------------------------------------------------------------
# Background live-results poller.
#
# While a group-stage match is being played, a daemon thread polls
# football-data.org (at least once a minute) and writes the live scoreline
# (plus any goal/card events the API exposes) into data/actuals.json, then
# invalidates the cached "current" simulation so projections refresh. It stops
# polling frequently once no match is in play. See app/live_source.py.
# ----------------------------------------------------------------------

_live_poller_started = False


def _live_poller_loop(app):
    import time
    from app import live_source

    global _live_version, _live_processing, _live_any_live

    # Polls the default (today: only) tournament. live_source's results feed
    # is itself WC2026-specific (FOOTBALL_DATA_URL); scoping this loop to
    # iterate several tournaments, each against its own results source, is
    # Stage 3 work done alongside wiring up a second tournament's feed.
    engine = get_engine()
    while True:
        delay = live_source.IDLE_MAX
        try:
            summary = live_source.poll_live_matches(engine)
            any_live = summary.get("any_live", False)
            _live_any_live = any_live
            if summary.get("changed"):
                invalidate_results("current")
                _live_processing = True
                try:
                    get_or_run_results(_POLLER_USER, "current")
                    _live_version += 1
                except Exception:
                    app.logger.exception("live poller: re-simulation failed")
                finally:
                    _live_processing = False
            if summary.get("error"):
                delay = max(live_source.LIVE_INTERVAL, 120)
            else:
                delay = live_source.compute_poll_delay(engine, any_live)
        except Exception:
            app.logger.exception("live poller iteration failed")
            delay = 120
        time.sleep(delay)


def _maybe_start_live_poller(app):
    global _live_poller_started
    if _live_poller_started:
        return
    if os.environ.get("DISABLE_LIVE_POLLER", "").lower() in ("1", "true", "yes"):
        return
    if app.config.get("TESTING"):
        return
    # ``create_app()`` runs (in run.py) before ``app.run(debug=...)`` sets
    # ``app.debug``, so infer debug from FLASK_DEBUG exactly as run.py does.
    # Under the Werkzeug reloader the watcher parent re-execs a child that has
    # WERKZEUG_RUN_MAIN=="true"; only that child should own the poller, so we
    # don't poll twice in debug mode. In production (FLASK_DEBUG=0, no
    # reloader) the guard is inert and the poller starts normally.
    debug = os.environ.get("FLASK_DEBUG", "1") not in ("0", "false", "False")
    if debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    import threading
    _live_poller_started = True
    threading.Thread(target=_live_poller_loop, args=(app,), daemon=True,
                     name="live-poller").start()
    threading.Thread(target=_warm_checkpoints_loop, args=(app,), daemon=True,
                     name="checkpoint-warmer").start()


def _warm_checkpoints_loop(app):
    """One-shot background thread: pre-warm all played match-checkpoint
    scenarios at a low N so team-page chart loads don't block on cold sims."""
    import time
    time.sleep(5)  # let the live poller warm "current" first
    try:
        with app.app_context():
            from app import data_store
            engine = get_engine()
            checkpoints = data_store.ordered_match_checkpoints(engine)
            actuals = data_store.load_actuals()
            played_pairs = set()
            for gname, entries in actuals.get("group_results", {}).items():
                for e in entries:
                    played_pairs.add((gname, frozenset((e.get("home"), e.get("away")))))
            ko_played = {int(k) for k in actuals.get("knockout_results", {}).keys()}

            for cp in checkpoints:
                if cp["kind"] == "group":
                    if (cp["group"], frozenset((cp["home"], cp["away"]))) not in played_pairs:
                        continue
                elif cp["kind"] == "knockout":
                    if cp.get("match_no") not in ko_played:
                        continue
                sid = data_store.match_scenario_id(cp["index"])
                if get_simulation_results(_POLLER_USER, sid) is None:
                    try:
                        get_or_run_results(_POLLER_USER, sid, n=10_000)
                    except Exception:
                        app.logger.exception("checkpoint warmer: failed for %s", sid)
    except Exception:
        app.logger.exception("checkpoint warmer thread failed")
