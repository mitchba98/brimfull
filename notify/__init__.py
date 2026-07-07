import importlib
import pkgutil
import json
import logging
import os

logger = logging.getLogger(__name__)
_handlers = {}

for _, name, _ in pkgutil.iter_modules([os.path.dirname(__file__)]):
    mod = importlib.import_module(f"notify.{name}")
    if hasattr(mod, "CHANNEL"):
        _handlers[mod.CHANNEL] = mod


def get_handlers():
    return sorted(_handlers.values(), key=lambda h: h.LABEL)


def _build_footer():
    base_url = os.environ.get("BASE_URL", "").rstrip("/")
    footer = "\n\n---\nPowered by Brimfull — https://brimfull.dev"
    if base_url:
        footer += f" | {base_url}"
    return footer


def send_alert(conn, account_id, title, message, priority="default"):
    from db import _decrypt_config
    configs = conn.execute(
        "SELECT * FROM notification_config WHERE account_id = ? AND enabled = 1",
        (account_id,),
    ).fetchall()
    logger.info("send_alert: title=%r configs=%d", title, len(configs))
    full_message = message + _build_footer()
    sent = False
    for cfg_row in configs:
        try:
            handler = _handlers.get(cfg_row["channel"])
            if handler:
                config = json.loads(_decrypt_config(cfg_row["config_json"]))
                handler.send(config, title, full_message, priority)
                logger.info("send_alert: sent via %s", cfg_row["channel"])
                sent = True
        except Exception:
            logger.exception("send_alert: failed via %s", cfg_row["channel"])
    return sent
