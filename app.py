import os
import json
import logging
import pathlib

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

from flask import Flask, request, Response, g, jsonify, render_template, redirect, url_for, send_file, flash
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
import db
import jobs as _jobs

assert os.environ.get("ADMIN_PASSWORD"), "ADMIN_PASSWORD env var required"

assert os.environ.get("BASE_URL"), "BASE_URL env var required (e.g. https://brimfull.yourdomain.com)"
BASE_URL = os.environ["BASE_URL"].rstrip("/")

APP_VERSION = json.loads((pathlib.Path(__file__).parent / "version.json").read_text())["version"]
GITHUB_URL = "https://github.com/mitchba98/brimfull"
SITE_URL = "https://brimfull.dev"
DENY_SETTINGS = bool(os.environ.get("DENY_SETTINGS"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
assert os.environ.get("SECRET_KEY"), "SECRET_KEY env var required"
app.secret_key = os.environ["SECRET_KEY"]
UNPROTECTED_PREFIXES = ("/api/", "/agent/")


@app.context_processor
def inject_globals():
    return {"app_version": APP_VERSION, "site_url": SITE_URL, "github_url": GITHUB_URL, "readonly": DENY_SETTINGS}


@app.before_request
def require_auth():
    if request.path.startswith(UNPROTECTED_PREFIXES[0]):
        key = request.headers.get("X-Brimfull-Key")
        conn = db.get_db()
        account = db.get_account_by_key(conn, key)
        conn.close()
        if account:
            return
        # Also accept Basic Auth for browser-facing API endpoints (e.g. history charts)
        auth = request.authorization
        if auth and auth.password == os.environ["ADMIN_PASSWORD"]:
            return
        return jsonify({"error": "Unauthorized"}), 401
    if request.path.startswith(UNPROTECTED_PREFIXES[1]):
        return
    auth = request.authorization
    if not auth or auth.password != os.environ["ADMIN_PASSWORD"]:
        return Response(
            "Unauthorized", 401,
            {"WWW-Authenticate": 'Basic realm="Brimfull"'},
        )


@app.template_filter("timeago")
def timeago_filter(dt_str):
    if not dt_str:
        return "never"
    dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def compute_status(server, thresholds):
    # server must be a plain dict (callers: pass dict(row) with metrics/worst_disk keys added)
    if not server["last_seen_at"]:
        return "offline"
    dt = datetime.fromisoformat(server["last_seen_at"]).replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - dt).total_seconds() > 600:
        return "offline"
    m = server["metrics"]
    if not m:
        return "ok"
    wd = server["worst_disk"]
    disk_pct = wd["percent_used"] if wd else 0
    cpu = m["cpu_percent"] or 0
    mem = m["mem_percent"] or 0
    if (cpu >= thresholds["cpu_critical"] or mem >= thresholds["mem_critical"]
            or disk_pct >= thresholds["disk_critical"]):
        return "critical"
    if (cpu >= thresholds["cpu_warning"] or mem >= thresholds["mem_warning"]
            or disk_pct >= thresholds["disk_warning"]):
        return "warning"
    return "ok"


@app.route("/")
def index():
    conn = db.get_db()
    try:
        account = db.get_account(conn)
        thresholds = db.get_thresholds(conn, account["id"])
        servers = db.get_servers_with_latest_metrics(conn, account["id"])
        for s in servers:
            if s["metrics"]:
                m = s["metrics"]
                m["cpu_percent"] = m["cpu_percent"] or 0
                m["mem_percent"] = m["mem_percent"] or 0
            if s["worst_disk"]:
                s["worst_disk"]["percent_used"] = s["worst_disk"]["percent_used"] or 0
            s["status"] = compute_status(s, thresholds)
        servers.sort(key=lambda s: {"critical": 0, "warning": 1, "offline": 2, "ok": 3}[s["status"]])
        return render_template("index.html", servers=servers, thresholds=thresholds)
    finally:
        conn.close()


@app.route("/api/v1/ingest", methods=["POST"])

def ingest():
    key = request.headers.get("X-Brimfull-Key", "")
    conn = db.get_db()
    try:
        account = db.get_account_by_key(conn, key)
        if not account:
            return jsonify({"ok": False, "error": "invalid key"}), 401
        data = request.get_json(force=True, silent=True)
        if not data or "hostname" not in data:
            return jsonify({"ok": False, "error": "invalid payload"}), 400
        import re
        hostname = data["hostname"]
        if not hostname or len(hostname) > 253 or not re.match(r'^[A-Za-z0-9._-]+$', hostname):
            return jsonify({"ok": False, "error": "invalid hostname"}), 400
        server_id = db.get_or_create_server(
            conn, account["id"], data["hostname"],
            request.remote_addr, data.get("version"),
        )
        db.insert_metrics(conn, server_id, data)
        db.insert_disk_metrics(conn, server_id, data.get("collected_at"), data.get("disks", []))
        latest = db.get_latest_version(conn)
        agent_ver = data.get("version", "")
        update = agent_ver != latest
        return jsonify({
            "ok": True,
            "agent_latest": latest,
            "update_available": update,
            "update_url": "/agent/agent.sh" if update else None,
        })
    finally:
        conn.close()


@app.route("/server/<int:server_id>")
def server_detail(server_id):
    conn = db.get_db()
    try:
        server = db.get_server(conn, server_id)
        account = db.get_account(conn)
        if not server or server["account_id"] != account["id"]:
            return "Not found", 404
        thresholds = db.get_thresholds(conn, account["id"])
        metrics = conn.execute(
            "SELECT * FROM metrics WHERE server_id = ? ORDER BY collected_at DESC LIMIT 1",
            (server_id,),
        ).fetchone()
        disks = db.get_server_disks(conn, server_id)
        alerts = conn.execute(
            "SELECT * FROM alerts WHERE server_id = ? ORDER BY triggered_at DESC LIMIT 50",
            (server_id,),
        ).fetchall()
        server = dict(server)
        server["metrics"] = dict(metrics) if metrics else None
        server["worst_disk"] = dict(disks[0]) if disks else None
        server["status"] = compute_status(server, thresholds)
        return render_template("server.html", server=server, disks=disks, thresholds=thresholds, alerts=alerts)
    finally:
        conn.close()


@app.route("/api/v1/server/<int:server_id>/history")
def server_history(server_id):
    hours = request.args.get("hours", 24, type=int)
    hours = min(hours, 8760)  # cap at 1 year
    conn = db.get_db()
    try:
        account = db.get_account(conn)
        server = db.get_server(conn, server_id)
        if not server or server["account_id"] != account["id"]:
            return jsonify({"error": "not found"}), 404
        every = 6 if hours <= 24 else 24 if hours <= 168 else 72
        metrics, disks = db.get_server_history(conn, server_id, hours, every)
        return jsonify({"metrics": metrics, "disks": disks})
    finally:
        conn.close()


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if DENY_SETTINGS:
        return redirect(url_for("index"))
    conn = db.get_db()
    try:
        account = db.get_account(conn)
        if request.method == "POST":
            action = request.form.get("action")
            if action == "rotate_key":
                db.rotate_api_key(conn, account["id"])
                flash("API key rotated.", "success")
            elif action == "save_thresholds":
                db.save_thresholds(conn, account["id"], {
                    k: float(request.form.get(k, d))
                    for k, d in [
                        ("cpu_warning", 70), ("cpu_critical", 90),
                        ("mem_warning", 75), ("mem_critical", 90),
                        ("disk_warning", 75), ("disk_critical", 90),
                    ]
                })
                flash("Thresholds saved.", "success")
            elif action == "save_channel":
                import notify as _notify
                channel = request.form.get("channel", "")
                handler = _notify._handlers.get(channel)
                if handler:
                    existing_rows = db.get_notification_configs(conn, account["id"])
                    existing = next((json.loads(r["config_json"]) for r in existing_rows if r["channel"] == channel), {})
                    config = {}
                    for f in handler.FIELDS:
                        submitted = request.form.get(f["name"], "")
                        if f["type"] == "password" and not submitted:
                            config[f["name"]] = existing.get(f["name"], "")
                        else:
                            config[f["name"]] = submitted
                    enabled = bool(request.form.get(f"{channel}_enabled"))
                    db.save_notification_config(conn, account["id"], channel, json.dumps(config), enabled)
                    flash(f"{handler.LABEL} config saved.", "success")
            elif action == "test_notify":
                import notify as _notify
                _notify.send_alert(conn, account["id"],
                    "Brimfull test notification",
                    "If you see this, notifications are working.", "default")
                flash("Test notification sent.", "info")
            elif action == "delete_server":
                server_id = request.form.get("server_id", type=int)
                if server_id:
                    db.delete_server(conn, server_id, account["id"])
                    flash("Server deleted.", "success")
            elif action == "mute_server":
                server_id = request.form.get("server_id", type=int)
                muted = request.form.get("muted") == "1"
                if server_id:
                    db.mute_server(conn, server_id, account["id"], muted)
                    flash("Server updated.", "success")
            return redirect(url_for("settings"))

        import notify as _notify
        thresholds = db.get_thresholds(conn, account["id"])
        notif_rows = db.get_notification_configs(conn, account["id"])
        notif = {r["channel"]: dict(json.loads(r["config_json"]), enabled=bool(r["enabled"])) for r in notif_rows}
        servers = db.get_all_servers(conn, account["id"])
        return render_template("settings.html",
            account=account,
            thresholds=thresholds,
            notif=notif,
            handlers=_notify.get_handlers(),
            servers=servers,
            host_url=BASE_URL
        )
    finally:
        conn.close()


@app.route("/export/db")
def export_db():
    path = os.environ.get("DB_PATH", "/data/brimfull.db")
    return send_file(path, as_attachment=True, download_name="brimfull.db")


@app.route("/agent/agent.sh")
def agent_download():
    p = pathlib.Path(__file__).parent / "agent.sh"
    if not p.exists():
        return "Not found", 404
    return send_file(str(p), mimetype="text/plain", as_attachment=True, download_name="brimfull-agent.sh")


# Startup
db.init_db()

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(_jobs.check_alerts, "interval", seconds=60, id="alert_check")
scheduler.add_job(_jobs.run_retention, "cron", hour=3, minute=0, id="retention")
scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
