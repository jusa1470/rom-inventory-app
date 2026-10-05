"""
Flask application factory.
Run:  python app.py
or:   flask --app app run
"""

import logging
import os

from flask import Flask, send_from_directory
from flask_session import Session

import config
import db.database as db
from routes.auth          import bp as auth_bp
from routes.api_settings  import bp as settings_bp
from routes.api_shopify   import bp as shopify_bp
from routes.api_products  import bp as products_bp
from routes.api_orders    import bp as orders_bp
from routes.api_rules     import bp as rules_bp
from services.auth_utils  import get_secret_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


def create_app() -> Flask:
    app = Flask(__name__, static_folder="frontend/static", static_url_path="/static")

    # ── Session config ─────────────────────────────────────────────
    os.makedirs(config.SESSION_DIR, exist_ok=True)
    app.secret_key                = get_secret_key()
    app.config["SESSION_TYPE"]    = "filesystem"
    app.config["SESSION_FILE_DIR"]= config.SESSION_DIR
    app.config["SESSION_PERMANENT"]= False
    app.config["SESSION_USE_SIGNER"]= True
    Session(app)

    # ── Blueprints ─────────────────────────────────────────────────
    for bp in (auth_bp, settings_bp, shopify_bp, products_bp, orders_bp, rules_bp):
        app.register_blueprint(bp)

    # ── Ensure Webami Creds ────────────────────────────────────────
    @app.before_request
    def _ensure_webami_creds():
        from flask import session as s
        from webami.session import configure as _cfg, _creds
        if s.get("authenticated") and not _creds.get("webami_username"):
            wu = s.get("webami_username") or ""
            wp = s.get("webami_password") or ""
            wb = s.get("webami_base_url") or config.WEBAMI_BASE_URL
            if wu and wp:
                _cfg(wb, wu, wp)

    # ── Serve the SPA ──────────────────────────────────────────────
    @app.route("/")
    def index():
        return send_from_directory("frontend", "index.html")

    @app.route("/js/<path:path>")
    def js_files(path: str):
        return send_from_directory("frontend/js", path)

    # ── Teardown: close per-thread DB connection ───────────────────
    @app.teardown_appcontext
    def close_db(_):
        import db.database as _db
        import threading
        conn = getattr(_db._local, "conn", None)
        if conn:
            try:
                conn.close()
            except Exception:
                pass
            _db._local.conn = None

    # ── Init DB ────────────────────────────────────────────────────
    with app.app_context():
        db.init_db()

    return app


app = create_app()

if __name__ == "__main__":
    print("\n  InventorySync running → http://localhost:5000\n")
    app.run(host="localhost", port=5000, debug=True, use_reloader=True, threaded=True)
