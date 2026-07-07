import json
import urllib.error
import urllib.request

CHANNEL = "telegram"
LABEL = "Telegram"
FIELDS = [
    {"name": "bot_token", "label": "Bot token", "type": "text", "placeholder": ""},
    {"name": "chat_id", "label": "Chat ID", "type": "text", "placeholder": ""},
]


def send(config, title, message, priority="default"):
    bot_token = config.get("bot_token", "")
    chat_id = config.get("chat_id", "")
    if not bot_token or not chat_id:
        return
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": f"{title}\n\n{message}"}).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram API error {e.code}: {body}") from None
