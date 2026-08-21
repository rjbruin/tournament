import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    # Debug is OPT-IN. It used to default to on, which meant the deployed
    # service ran the Werkzeug reloader (a second full copy of the process)
    # and, more seriously, served the interactive debugger — a remote-code-
    # execution surface — on a public port. Local development sets
    # FLASK_DEBUG=1 explicitly (see .claude/launch.json).
    debug = os.environ.get("FLASK_DEBUG", "0") in ("1", "true", "True")
    app.run(debug=debug, port=port, host=os.environ.get("HOST", "127.0.0.1"))
