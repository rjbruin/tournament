import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    debug = os.environ.get("FLASK_DEBUG", "1") not in ("0", "false", "False")
    app.run(debug=debug, port=port, host=os.environ.get("HOST", "127.0.0.1"))
