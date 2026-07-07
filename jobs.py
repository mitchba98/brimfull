from datetime import datetime, timezone
from collections import defaultdict
import logging
import db
import notify  # noqa: imported for monkeypatching in tests

logger = logging.getLogger(__name__)


def check_alerts():
    conn = db.get_db()
    try:
        accounts = conn.execute("SELECT * FROM accounts").fetchall()
        for account in accounts:
            thresholds = db.get_thresholds(conn, account["id"])
            servers = conn.execute(
                "SELECT * FROM servers WHERE account_id = ? AND is_active = 1 AND alert_enabled = 1 AND muted = 0",
                (account["id"],),
            ).fetchall()
            for server in servers:
                _check_offline(conn, server, account)
                _check_resources(conn, server, account, thresholds)
    finally:
        conn.close()


def _now():
    return datetime.now(timezone.utc)


def _parse(dt_str):
    return datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)


def _check_offline(conn, server, account):
    last = server["last_seen_at"]
    if not last:
        return
    is_offline = (_now() - _parse(last)).total_seconds() > 600
    existing = conn.execute(
        "SELECT * FROM alerts WHERE server_id = ? AND alert_type = 'offline' AND resolved_at IS NULL",
        (server["id"],),
    ).fetchone()
    if is_offline and not existing:
        conn.execute(
            "INSERT INTO alerts (server_id, alert_type, triggered_at, notification_count) VALUES (?, 'offline', datetime('now'), 0)",
            (server["id"],),
        )
        conn.commit()
        alert_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        sent = notify.send_alert(conn, account["id"],
            f"{server['hostname']} is offline",
            "No check-in for more than 10 minutes.", "urgent")
        if sent:
            conn.execute(
                "UPDATE alerts SET last_notified_at = datetime('now'), notification_count = 1 WHERE id = ?",
                (alert_id,),
            )
            conn.commit()
    elif is_offline and existing:
        lna = existing["last_notified_at"]
        if ((_now() - _parse(lna)).total_seconds() if lna else float("inf")) > 600:
            sent = notify.send_alert(conn, account["id"],
                f"{server['hostname']} still offline",
                "Still no check-in.", "urgent")
            if sent:
                conn.execute(
                    "UPDATE alerts SET last_notified_at = datetime('now'), notification_count = notification_count + 1 WHERE id = ?",
                    (existing["id"],),
                )
                conn.commit()
    elif not is_offline and existing:
        conn.execute("UPDATE alerts SET resolved_at = datetime('now') WHERE id = ?", (existing["id"],))
        conn.commit()
        notify.send_alert(conn, account["id"],
            f"{server['hostname']} is back online",
            "Server has checked in.", "default")


def _check_resources(conn, server, account, thresholds):
    recent = conn.execute(
        "SELECT * FROM metrics WHERE server_id = ? ORDER BY collected_at DESC LIMIT 2",
        (server["id"],),
    ).fetchall()
    logger.info("check_resources: %s has %d metric rows", server["hostname"], len(recent))
    if len(recent) < 2:
        return  # need 2 consecutive readings to avoid flapping

    for col, alert_type, warn_k, crit_k, label in [
        ("cpu_percent", "cpu", "cpu_warning", "cpu_critical", "CPU"),
        ("mem_percent", "mem", "mem_warning", "mem_critical", "Memory"),
    ]:
        vals = [r[col] for r in recent if r[col] is not None]
        if len(vals) < 2:
            continue
        if all(v >= thresholds[crit_k] for v in vals):
            _fire_or_repeat(conn, account, server, alert_type, thresholds[crit_k], label, "critical")
        elif all(v >= thresholds[warn_k] for v in vals):
            _fire_or_repeat(conn, account, server, alert_type, thresholds[warn_k], label, "warning")
        else:
            _resolve(conn, account, server, alert_type, None)

    # Disk: group last 200 disk rows by mount, take last 2 per mount
    disk_rows = conn.execute(
        "SELECT mount_point, percent_used FROM disk_metrics WHERE server_id = ? ORDER BY collected_at DESC LIMIT 200",
        (server["id"],),
    ).fetchall()
    by_mount = defaultdict(list)
    for d in disk_rows:
        by_mount[d["mount_point"]].append(d["percent_used"])

    for mount, vals in by_mount.items():
        vals = vals[:2]
        if len(vals) < 2:
            continue
        logger.info("check_resources: %s %s disk vals=%s warn=%.0f crit=%.0f",
                    server["hostname"], mount, vals, thresholds["disk_warning"], thresholds["disk_critical"])
        if all(v >= thresholds["disk_critical"] for v in vals):
            _fire_or_repeat(conn, account, server, "disk", thresholds["disk_critical"], f"Disk {mount}", "critical", mount)
        elif all(v >= thresholds["disk_warning"] for v in vals):
            _fire_or_repeat(conn, account, server, "disk", thresholds["disk_warning"], f"Disk {mount}", "warning", mount)
        else:
            _resolve(conn, account, server, "disk", mount)


def _fire_or_repeat(conn, account, server, alert_type, threshold, label, severity, mount=None):
    existing = conn.execute(
        """SELECT * FROM alerts WHERE server_id = ? AND alert_type = ?
           AND (mount_point IS ? OR mount_point = ?) AND resolved_at IS NULL""",
        (server["id"], alert_type, mount, mount),
    ).fetchone()
    icon = "🔴" if severity == "critical" else "🟡"
    if not existing:
        conn.execute(
            """INSERT INTO alerts (server_id, alert_type, mount_point, threshold_percent, triggered_at, notification_count)
               VALUES (?, ?, ?, ?, datetime('now'), 0)""",
            (server["id"], alert_type, mount, threshold),
        )
        conn.commit()
        alert_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        sent = notify.send_alert(conn, account["id"],
            f"{icon} {server['hostname']}: {label} {severity}",
            f"{label} is at or above {threshold:.0f}% on {server['hostname']}.",
            "urgent" if severity == "critical" else "default")
        if sent:
            conn.execute(
                "UPDATE alerts SET last_notified_at = datetime('now'), notification_count = 1 WHERE id = ?",
                (alert_id,),
            )
            conn.commit()
    else:
        lna = existing["last_notified_at"]
        elapsed = (_now() - _parse(lna)).total_seconds() if lna else float("inf")
        logger.info("fire_or_repeat: %s %s existing alert, %.0fs since last notify (need 3600)", server["hostname"], alert_type, elapsed)
        if elapsed > 3600:
            sent = notify.send_alert(conn, account["id"],
                f"{icon} {server['hostname']}: {label} still {severity}",
                f"{label} still above {threshold:.0f}% on {server['hostname']}.",
                "urgent" if severity == "critical" else "default")
            if sent:
                conn.execute(
                    "UPDATE alerts SET last_notified_at = datetime('now'), notification_count = notification_count + 1 WHERE id = ?",
                    (existing["id"],),
                )
                conn.commit()


def _resolve(conn, account, server, alert_type, mount):
    existing = conn.execute(
        """SELECT * FROM alerts WHERE server_id = ? AND alert_type = ?
           AND (mount_point IS ? OR mount_point = ?) AND resolved_at IS NULL""",
        (server["id"], alert_type, mount, mount),
    ).fetchone()
    if existing:
        conn.execute("UPDATE alerts SET resolved_at = datetime('now') WHERE id = ?", (existing["id"],))
        conn.commit()
        notify.send_alert(conn, account["id"],
            f"🟢 {server['hostname']}: {alert_type}{' ' + mount if mount else ''} resolved",
            f"Metric is back below threshold on {server['hostname']}.",
            "default")


def run_retention():
    conn = db.get_db()
    try:
        # Delete >90 days
        conn.execute("DELETE FROM metrics WHERE collected_at < datetime('now', '-90 days')")
        conn.execute("DELETE FROM disk_metrics WHERE collected_at < datetime('now', '-90 days')")
        # 7-30 days: keep one row per server per hour
        conn.execute("""
            DELETE FROM metrics WHERE id NOT IN (
                SELECT MAX(id) FROM metrics
                WHERE collected_at < datetime('now', '-7 days')
                  AND collected_at >= datetime('now', '-30 days')
                GROUP BY server_id, strftime('%Y-%m-%d %H', collected_at)
            ) AND collected_at < datetime('now', '-7 days')
              AND collected_at >= datetime('now', '-30 days')
        """)
        conn.execute("""
            DELETE FROM disk_metrics WHERE id NOT IN (
                SELECT MAX(id) FROM disk_metrics
                WHERE collected_at < datetime('now', '-7 days')
                  AND collected_at >= datetime('now', '-30 days')
                GROUP BY server_id, mount_point, strftime('%Y-%m-%d %H', collected_at)
            ) AND collected_at < datetime('now', '-7 days')
              AND collected_at >= datetime('now', '-30 days')
        """)
        # 30-90 days: keep one row per server per day
        conn.execute("""
            DELETE FROM metrics WHERE id NOT IN (
                SELECT MAX(id) FROM metrics
                WHERE collected_at < datetime('now', '-30 days')
                  AND collected_at >= datetime('now', '-90 days')
                GROUP BY server_id, strftime('%Y-%m-%d', collected_at)
            ) AND collected_at < datetime('now', '-30 days')
              AND collected_at >= datetime('now', '-90 days')
        """)
        conn.execute("""
            DELETE FROM disk_metrics WHERE id NOT IN (
                SELECT MAX(id) FROM disk_metrics
                WHERE collected_at < datetime('now', '-30 days')
                  AND collected_at >= datetime('now', '-90 days')
                GROUP BY server_id, mount_point, strftime('%Y-%m-%d', collected_at)
            ) AND collected_at < datetime('now', '-30 days')
              AND collected_at >= datetime('now', '-90 days')
        """)
        conn.commit()
    finally:
        conn.close()
