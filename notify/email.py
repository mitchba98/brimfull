import smtplib
from email.mime.text import MIMEText

CHANNEL = "email"
LABEL = "Email"
FIELDS = [
    {"name": "smtp_host", "label": "SMTP host", "type": "text", "placeholder": "smtp.gmail.com"},
    {"name": "smtp_port", "label": "Port", "type": "text", "placeholder": "587"},
    {"name": "smtp_user", "label": "Username", "type": "text", "placeholder": ""},
    {"name": "smtp_pass", "label": "Password", "type": "password", "placeholder": ""},
    {"name": "from_addr", "label": "From address", "type": "email", "placeholder": ""},
    {"name": "to_addr", "label": "To address", "type": "email", "placeholder": ""},
]


def send(config, title, message, priority="default"):
    smtp_host = config.get("smtp_host", "")
    if not smtp_host:
        return
    msg = MIMEText(message)
    msg["Subject"] = f"Brimfull Notification - {title}"
    msg["From"] = config.get("from_addr", "")
    msg["To"] = config.get("to_addr", "")
    with smtplib.SMTP(smtp_host, int(config.get("smtp_port", 587))) as s:
        s.starttls()
        s.login(config.get("smtp_user", ""), config.get("smtp_pass", ""))
        s.sendmail(config.get("from_addr", ""), [config.get("to_addr", "")], msg.as_string())
