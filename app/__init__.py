import json
import os
import secrets

from flask import Flask, abort, redirect, request, session, url_for
from flask_login import LoginManager, current_user

from app import auth
from app.simulation.engine import SimulationEngine
from app.flags import flag_emoji

# Per-account in-memory simulation results: {username: results_dict}.
# Snapshots are persisted to disk (see data_store), but the "current" results
# only live in memory and are lost on restart — the user can re-run the
# simulation from their last snapshot's settings.
_simulation_results: dict[str, dict] = {}
_engine: SimulationEngine = None


def get_engine() -> SimulationEngine:
    return _engine


def get_simulation_results(username: str):
    return _simulation_results.get(username.lower()) if username else None


def set_simulation_results(username: str, results) -> None:
    _simulation_results[username.lower()] = results


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
    global _engine

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

    data_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "wc2026.json")
    with open(data_path) as f:
        tournament_data = json.load(f)

    _engine = SimulationEngine(tournament_data)

    from app.web.routes import web_bp
    from app.web.auth_routes import auth_bp
    from app.api.routes import api_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        return auth.get_user(user_id)

    login_manager.init_app(app)

    @app.before_request
    def require_login():
        # Allow unauthenticated access only to the auth pages and static
        # assets. Everything else (including the API, which uses its own
        # session-or-api-slug check) requires a logged-in account.
        if request.endpoint is None:
            return
        if request.endpoint == "static" or request.endpoint.startswith("auth."):
            return
        if request.blueprint == "api":
            return
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.full_path))

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

    app.jinja_env.filters["flag"] = flag_emoji

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
        tz_name = tz_name or "UTC"
        try:
            dt = datetime.fromisoformat(f"{match['date']}T{match['local_time']}")
            dt = dt.replace(tzinfo=ZoneInfo(venue_tz))
            dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            return f"{match['date']} {match['local_time']}"
        return dt.strftime(fmt)

    @app.context_processor
    def inject_settings():
        if current_user.is_authenticated:
            return {"app_settings": current_user.settings, "current_user": current_user}
        return {"app_settings": auth.DEFAULT_USER_SETTINGS, "current_user": current_user}

    return app
