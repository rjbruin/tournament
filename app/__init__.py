import json
import os
from flask import Flask

from app.simulation.engine import SimulationEngine
from app.flags import flag_emoji

_simulation_results = None
_engine: SimulationEngine = None


def get_engine() -> SimulationEngine:
    return _engine


def get_simulation_results():
    return _simulation_results


def set_simulation_results(results):
    global _simulation_results
    _simulation_results = results


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

    url_prefix = os.environ.get("URL_PREFIX", "").strip()
    if url_prefix:
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, url_prefix)

    data_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "wc2026.json")
    with open(data_path) as f:
        tournament_data = json.load(f)

    _engine = SimulationEngine(tournament_data)

    from app.web.routes import web_bp
    from app.api.routes import api_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    app.jinja_env.filters["flag"] = flag_emoji

    @app.template_filter("local_time")
    def local_time(match, settings_tz=None, fmt="%a %d %b, %H:%M"):
        """Convert a fixture's local kickoff (date + local_time +
        local_timezone, e.g. venue's local time) to the configured display
        timezone."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from app import data_store

        if not match or not match.get("date") or not match.get("local_time"):
            return ""
        venue_tz = match.get("local_timezone") or "UTC"
        tz_name = settings_tz or data_store.load_settings().get("display_timezone", "UTC")
        try:
            dt = datetime.fromisoformat(f"{match['date']}T{match['local_time']}")
            dt = dt.replace(tzinfo=ZoneInfo(venue_tz))
            dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            return f"{match['date']} {match['local_time']}"
        return dt.strftime(fmt)

    @app.context_processor
    def inject_settings():
        from app import data_store
        return {"app_settings": data_store.load_settings()}

    return app
