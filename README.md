# Brimfull [Knows before it overflows]

**[brimfull.dev](https://brimfull.dev)** — Simple server monitoring for disk, CPU, and memory. [![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE) Get alerted before a drive fills up, a server goes offline, or memory spikes — without the complexity of Grafana or Prometheus. No ports to open, ssh tunnels to create, or binary agents to install. Just a simple shell script, posting to a server.

**How it works:** A small shell script runs on each server you want to monitor (via crontab) and posts metrics to your Brimfull instance every 5 minutes.

## Requirements

- A server to run Brimfull on (any VPS with Docker works)
- Docker and Docker Compose installed

## Setup

**1. Clone the repo and configure:**

```bash
git clone git@github.com:mitchba98/brimfull.git
cd brimfull
```

Create a `.env` file with your settings:

```bash
ADMIN_PASSWORD=yourpassword
SECRET_KEY=        # generate with: openssl rand -hex 32
BASE_URL=https://brimfull.yourdomain.com
```

**2. Start it:**

```bash
docker compose up -d
```

Open `http://your-server:5000` and log in with your `ADMIN_PASSWORD`.

**3. Add a server to monitor:**

Go you your settings page, which will give you the script / BRIMFULL_KEY to install on your monitored server.

Add this to the root crontab. Within 5 minutes the server will appear in your dashboard.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ADMIN_PASSWORD` | Yes | Password for the web dashboard |
| `SECRET_KEY` | Yes | Session secret — generate with `openssl rand -hex 32` |
| `BASE_URL` | Yes | Full URL of your Brimfull instance (e.g. `https://brimfull.example.com`) |
| `API_KEY` | No | If set, the agent must include this key with every check-in |
| `DB_PATH` | No | Path to the SQLite database file (default: `/data/brimfull.db`) |
| `DENY_SETTINGS` | No | Set to any value to disable the settings page (useful for shared/demo installs) |

## Putting it behind a reverse proxy

Brimfull runs on port 5000. To serve it over HTTPS, proxy it with Nginx or Caddy:

Example: 

**Caddy:**
```
brimfull.yourdomain.com {
    reverse_proxy localhost:5000
}
```

**Nginx:**
```nginx
server {
    listen 443 ssl;
    server_name brimfull.yourdomain.com;
    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Notifications

Configure alerts in **Settings**. Supported channels:

- **ntfy** — paste your ntfy topic, works instantly with no account
- **Telegram** — bot token + chat ID
- **Email** — any SMTP server (Gmail, Sendgrid, etc.)
- **Slack** — any Slack Webhook

## Data & Backups

Your data lives in `./data/brimfull.db` (SQLite). Back it up by copying that file, or download it any time from **Settings → Export DB**.

To move Brimfull to a new server: export the DB, copy `docker-compose.yml`, mount the DB on the new instance, and start it up.

To store it in a different path on the 

## Upgrading

```bash
git pull
docker compose up --build --force-recreate -d
```
