import json
import urllib.request

CHANNEL = "slack"
LABEL = "Slack"
FIELDS = [
    {"name": "webhook_url", "label": "Webhook URL", "type": "password", "placeholder": "https://hooks.slack.com/services/..."},
]


def send(config, title, message, priority="default"):
    webhook_url = config.get("webhook_url", "")
    if not webhook_url:
        return
    payload = json.dumps({"text": f"*{title}*\n{message}"}).encode()
    req = urllib.request.Request(webhook_url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    urllib.request.urlopen(req, timeout=10)
