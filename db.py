import os
import sqlite3
import secrets
import hashlib
import base64
from datetime import datetime, timezone
import logging
logger = logging.getLogger(__name__)

def _fernet():
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(os.environ["SECRET_KEY"].encode()).digest())
    return Fernet(key)

def _encrypt_config(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()

def _decrypt_config(value: str) -> str:
    if value.startswith("{"):  # legacy plaintext, not yet encrypted
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except Exception:
        return value

def get_db():
    path = os.environ.get("DB_PATH", "/data/brimfull.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY,
            api_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            hostname TEXT NOT NULL,
            label TEXT,
            ip_address TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen_at TEXT,
            agent_version TEXT,
            auto_update INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            alert_enabled INTEGER NOT NULL DEFAULT 1,
            muted INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY,
            server_id INTEGER NOT NULL REFERENCES servers(id),
            collected_at TEXT NOT NULL,
            cpu_load_1m REAL,
            cpu_cores INTEGER,
            cpu_percent REAL,
            mem_used_mb INTEGER,
            mem_total_mb INTEGER,
            mem_percent REAL,
            swap_used_mb INTEGER,
            swap_total_mb INTEGER,
            uptime_seconds INTEGER
        );
        CREATE TABLE IF NOT EXISTS disk_metrics (
            id INTEGER PRIMARY KEY,
            server_id INTEGER NOT NULL REFERENCES servers(id),
            collected_at TEXT NOT NULL,
            mount_point TEXT NOT NULL,
            device TEXT,
            used_gb REAL,
            total_gb REAL,
            percent_used REAL
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY,
            server_id INTEGER NOT NULL REFERENCES servers(id),
            alert_type TEXT NOT NULL,
            mount_point TEXT,
            threshold_percent REAL,
            triggered_at TEXT NOT NULL,
            resolved_at TEXT,
            last_notified_at TEXT,
            notification_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS notification_config (
            id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            channel TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS thresholds (
            id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            server_id INTEGER,
            cpu_warning REAL NOT NULL DEFAULT 70,
            cpu_critical REAL NOT NULL DEFAULT 90,
            mem_warning REAL NOT NULL DEFAULT 75,
            mem_critical REAL NOT NULL DEFAULT 90,
            disk_warning REAL NOT NULL DEFAULT 75,
            disk_critical REAL NOT NULL DEFAULT 90
        );
        CREATE TABLE IF NOT EXISTS agent_versions (
            version TEXT PRIMARY KEY,
            released_at TEXT NOT NULL DEFAULT (datetime('now')),
            is_latest INTEGER NOT NULL DEFAULT 0,
            notes TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_metrics_server_collected ON metrics(server_id, collected_at);
        CREATE INDEX IF NOT EXISTS idx_disk_server_collected ON disk_metrics(server_id, collected_at);
        CREATE INDEX IF NOT EXISTS idx_servers_account ON servers(account_id);
        CREATE INDEX IF NOT EXISTS idx_alerts_server ON alerts(server_id);
    """)
    # Seed default account if none exists
    if not conn.execute("SELECT id FROM accounts LIMIT 1").fetchone():
        key = os.environ.get("API_KEY") or secrets.token_hex(32)
        conn.execute("INSERT INTO accounts (api_key) VALUES (?)", (key,))
        account_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO thresholds (account_id) VALUES (?)", (account_id,))
        conn.execute("INSERT INTO agent_versions (version, is_latest) VALUES ('1.0.0', 1)")
        conn.commit()

    conn.close()


def get_account_by_key(conn, key):
    return conn.execute("SELECT * FROM accounts WHERE api_key = ?", (key,)).fetchone()


def get_account(conn):
    return conn.execute("SELECT * FROM accounts LIMIT 1").fetchone()


def get_latest_version(conn):
    row = conn.execute("SELECT version FROM agent_versions WHERE is_latest = 1").fetchone()
    return row["version"] if row else "1.0.0"


def get_or_create_server(conn, account_id, hostname, ip, agent_version=None):
    row = conn.execute(
        "SELECT id FROM servers WHERE account_id = ? AND hostname = ?",
        (account_id, hostname),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE servers SET last_seen_at = datetime('now'), ip_address = ?, agent_version = ? WHERE id = ?",
            (ip, agent_version, row["id"]),
        )
        conn.commit()
        return row["id"]
    conn.execute(
        "INSERT INTO servers (account_id, hostname, ip_address, agent_version, last_seen_at) VALUES (?, ?, ?, ?, datetime('now'))",
        (account_id, hostname, ip, agent_version),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def insert_metrics(conn, server_id, data):
    collected_at = data.get("collected_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cpu = data.get("cpu", {})
    mem = data.get("memory", {})
    swap = data.get("swap", {})
    conn.execute(
        """INSERT INTO metrics
           (server_id, collected_at, cpu_load_1m, cpu_cores, cpu_percent,
            mem_used_mb, mem_total_mb, mem_percent,
            swap_used_mb, swap_total_mb, uptime_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            server_id,
            collected_at,
            cpu.get("load_1m"), cpu.get("cores"), cpu.get("percent"),
            mem.get("used_mb"), mem.get("total_mb"), mem.get("percent"),
            swap.get("used_mb"), swap.get("total_mb"),
            data.get("uptime_seconds"),
        ),
    )
    conn.commit()


def get_thresholds(conn, account_id):
    row = conn.execute(
        "SELECT * FROM thresholds WHERE account_id = ? AND server_id IS NULL",
        (account_id,),
    ).fetchone()
    if row:
        return dict(row)
    return {
        "cpu_warning": 70, "cpu_critical": 90,
        "mem_warning": 75, "mem_critical": 90,
        "disk_warning": 75, "disk_critical": 90,
    }


def get_servers_with_latest_metrics(conn, account_id):
    servers = conn.execute(
        "SELECT * FROM servers WHERE account_id = ? AND is_active = 1 ORDER BY hostname",
        (account_id,),
    ).fetchall()
    result = []
    for s in servers:
        metrics = conn.execute(
            "SELECT * FROM metrics WHERE server_id = ? ORDER BY collected_at DESC LIMIT 1",
            (s["id"],),
        ).fetchone()
        worst_disk = conn.execute(
            """SELECT * FROM disk_metrics WHERE server_id = ?
               ORDER BY collected_at DESC, percent_used DESC LIMIT 1""",
            (s["id"],),
        ).fetchone()
        result.append(dict(s) | {
            "metrics": dict(metrics) if metrics else None,
            "worst_disk": dict(worst_disk) if worst_disk else None,
        })
    return result


def get_server(conn, server_id):
    return conn.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()


def get_server_disks(conn, server_id):
    """Latest disk reading per mount point."""
    return conn.execute(
        """SELECT * FROM disk_metrics WHERE server_id = ?
           AND collected_at = (SELECT MAX(collected_at) FROM disk_metrics WHERE server_id = ?)
           ORDER BY percent_used DESC""",
        (server_id, server_id),
    ).fetchall()


def get_server_history(conn, server_id, hours=24, every=1):
    metrics = conn.execute(
        """SELECT collected_at, cpu_percent, mem_percent FROM metrics
           WHERE server_id = ? AND collected_at >= datetime('now', ? || ' hours')
           ORDER BY collected_at ASC""",
        (server_id, f"-{hours}"),
    ).fetchall()
    mounts = conn.execute(
        """SELECT DISTINCT mount_point FROM disk_metrics
           WHERE server_id = ? AND collected_at >= datetime('now', ? || ' hours')""",
        (server_id, f"-{hours}"),
    ).fetchall()
    disks = {}
    for m in mounts:
        rows = conn.execute(
            """SELECT collected_at, percent_used FROM disk_metrics
               WHERE server_id = ? AND mount_point = ?
               AND collected_at >= datetime('now', ? || ' hours')
               ORDER BY collected_at ASC""",
            (server_id, m["mount_point"], f"-{hours}"),
        ).fetchall()
        disks[m["mount_point"]] = [{"t": r["collected_at"], "v": r["percent_used"]} for r in rows][::every]
    return (
        [{"t": r["collected_at"], "cpu": r["cpu_percent"], "mem": r["mem_percent"]} for r in metrics][::every],
        disks,
    )


def insert_disk_metrics(conn, server_id, collected_at, disks):
    if not collected_at:
        collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for disk in disks:
        conn.execute(
            """INSERT INTO disk_metrics
               (server_id, collected_at, mount_point, device, used_gb, total_gb, percent_used)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                server_id,
                collected_at,
                disk.get("mount"), disk.get("device"),
                disk.get("used_gb"), disk.get("total_gb"), disk.get("percent"),
            ),
        )
    conn.commit()


def save_thresholds(conn, account_id, data):
    existing = conn.execute(
        "SELECT id FROM thresholds WHERE account_id = ? AND server_id IS NULL", (account_id,)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE thresholds SET cpu_warning=?, cpu_critical=?, mem_warning=?, mem_critical=?,
               disk_warning=?, disk_critical=? WHERE id=?""",
            (data["cpu_warning"], data["cpu_critical"], data["mem_warning"],
             data["mem_critical"], data["disk_warning"], data["disk_critical"], existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO thresholds (account_id, cpu_warning, cpu_critical, mem_warning, mem_critical, disk_warning, disk_critical)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (account_id, data["cpu_warning"], data["cpu_critical"],
             data["mem_warning"], data["mem_critical"],
             data["disk_warning"], data["disk_critical"]),
        )
    conn.commit()


def get_notification_configs(conn, account_id):
    rows = conn.execute(
        "SELECT * FROM notification_config WHERE account_id = ?", (account_id,)
    ).fetchall()
    return [dict(r, config_json=_decrypt_config(r["config_json"])) for r in rows]


def save_notification_config(conn, account_id, channel, config_json, enabled):
    encrypted = _encrypt_config(config_json)
    existing = conn.execute(
        "SELECT id FROM notification_config WHERE account_id = ? AND channel = ?",
        (account_id, channel),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE notification_config SET config_json = ?, enabled = ? WHERE id = ?",
            (encrypted, 1 if enabled else 0, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO notification_config (account_id, channel, config_json, enabled) VALUES (?, ?, ?, ?)",
            (account_id, channel, encrypted, 1 if enabled else 0),
        )
    conn.commit()


def get_all_servers(conn, account_id):
    return conn.execute(
        "SELECT * FROM servers WHERE account_id = ? ORDER BY hostname",
        (account_id,),
    ).fetchall()


def delete_server(conn, server_id, account_id):
    conn.execute("DELETE FROM alerts WHERE server_id = ?", (server_id,))
    conn.execute("DELETE FROM disk_metrics WHERE server_id = ?", (server_id,))
    conn.execute("DELETE FROM metrics WHERE server_id = ?", (server_id,))
    conn.execute("DELETE FROM servers WHERE id = ? AND account_id = ?", (server_id, account_id))
    conn.commit()


def mute_server(conn, server_id, account_id, muted):
    conn.execute(
        "UPDATE servers SET muted = ? WHERE id = ? AND account_id = ?",
        (1 if muted else 0, server_id, account_id),
    )
    conn.commit()


def rotate_api_key(conn, account_id):
    new_key = secrets.token_hex(32)
    conn.execute("UPDATE accounts SET api_key = ? WHERE id = ?", (new_key, account_id))
    conn.commit()
    return new_key
