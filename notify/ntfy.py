import json
import urllib.request

CHANNEL = "ntfy"
LABEL = "ntfy.sh"
FIELDS = [
    {"name": "topic", "label": "Topic", "type": "text", "placeholder": "my-alerts"},
]


def send(config, title, message, priority="default"):
    topic = config.get("topic", "")
    if not topic:
        return
    priority_map = {"urgent": 5, "high": 4, "default": 3, "low": 2, "min": 1}
    payload = json.dumps({"topic": topic, "title": title, "message": message, "priority": priority_map.get(priority, 3)}).encode()
    req = urllib.request.Request("https://ntfy.sh", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    urllib.request.urlopen(req, timeout=10)
