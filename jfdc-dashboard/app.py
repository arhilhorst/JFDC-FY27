"""JFC Post-Event Recap & Strike Dashboard - web server.

Run:  python app.py        then open http://localhost:8000
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from jfdc import engine
from jfdc.sources import Table, make_source

BASE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("JFDC_CONFIG", BASE / "config.json"))

app = Flask(__name__, static_folder=str(BASE / "static"), static_url_path="/static")


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


class DataStore:
    """Caches the parsed data and reloads whenever a source reports a new version."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cache: dict = {}
        self.versions: tuple | None = None
        self.loaded_at = 0.0
        self.error: str | None = None

    def _sources(self, cfg: dict):
        return (
            make_source(cfg["recap_source"], BASE, "RECAP_SOURCE"),
            make_source(cfg["bills_source"], BASE, "BILLS_SOURCE", optional=True),
            make_source(cfg.get("adjustments_source", {"type": "file", "path": "strike_adjustments.csv"}), BASE,
                        "ADJUSTMENTS_SOURCE", optional=True),
        )

    def get(self, fy: int | None = None, force: bool = False) -> dict:
        cfg = load_config()
        today = date.fromisoformat(os.environ["JFDC_TODAY"]) if os.environ.get("JFDC_TODAY") else date.today()
        srcs = self._sources(cfg)
        versions = (CONFIG_PATH.stat().st_mtime_ns, str(today), fy) + tuple(s.version() for s in srcs)
        with self.lock:
            if force or versions != self.versions or not self.cache:
                try:
                    tables = [s.load() for s in srcs]
                    data = engine.build(tables[0], tables[1], tables[2], cfg, today, fy)
                    data["sources"] = [s.describe() for s in srcs]
                    data["refresh_seconds"] = cfg.get("refresh_seconds", 60)
                    self.cache, self.versions, self.error = data, versions, None
                    self.loaded_at = time.time()
                except Exception as e:  # keep serving the last good data
                    self.error = f"{type(e).__name__}: {e}"
                    if not self.cache:
                        raise
            out = dict(self.cache)
            out["loaded_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.loaded_at))
            out["error"] = self.error
            return out


store = DataStore()


@app.before_request
def basic_auth():
    """Optional password. Set DASHBOARD_PASSWORD when you deploy it anywhere public."""
    pw = os.environ.get("DASHBOARD_PASSWORD")
    if not pw:
        return None
    auth = request.authorization
    if auth and auth.password == pw:
        return None
    return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="JFC Dashboard"'})


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/data")
def api_data():
    fy = request.args.get("fy", type=int)
    force = request.args.get("refresh") == "1"
    try:
        return jsonify(store.get(fy, force))
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.get("/api/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=bool(os.environ.get("DEBUG")))
