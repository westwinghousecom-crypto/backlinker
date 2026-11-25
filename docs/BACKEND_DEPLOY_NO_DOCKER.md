# Backend deploy guide (no Docker)

Runs the FastAPI API on a plain Linux VPS with Python, systemd and Caddy. The frontend lives on Vercel; this guide only covers the API.

> Not tested end to end: written from the repo (`backend/Dockerfile`, `docs/DEPLOYMENT.md`, `backend/app/core/config.py`). Run the first
> deploy on staging and check `/health/ready` before sending real traffic.

## 0. Why a VPS and not Vercel/serverless

The API runs its background workers (IndexNow, backlink checks, Google inspections) **inside the one process**, and the rate limits and
Google quota window are **in memory**. It must be a long-lived process with **exactly one worker**. Serverless platforms (Vercel
functions, Lambda) will not work. Any always-on host does: a small VPS (Hetzner, DigitalOcean, Linode), Railway, Render or Fly.io.
Sections 1-6 use a VPS; section 8 maps the same settings to a PaaS.

## 1. Requirements

- Ubuntu 22.04/24.04 (or Debian 12) VPS, 1 vCPU / 1 GB RAM is enough to start.
- A DNS name for the API, e.g. `api.example.com`, pointing at the VPS. It must be **same-site with the Vercel domain** (e.g. app on
  `app.example.com` or `example.com`), because the Google sign-in cookie is only sent when both are same-site. A `*.vercel.app` URL plus
  a separate API domain will break Google connect: add a custom domain to the Vercel project.
- The Appwrite project and tables already created (see `backend/README.md`, `backend/GOOGLE_SETUP.md`).
- Python 3.14 is what the Dockerfile uses; use the newest Python your distro or `uv`/`pyenv` offers (3.12+ should be fine, unverified).

## 2. Install system packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git ufw debian-keyring debian-archive-keyring apt-transport-https curl
# Caddy (automatic HTTPS): https://caddyserver.com/docs/install#debian-ubuntu-raspbian
sudo apt install -y caddy
sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable
```

## 3. Create a service user and get the code

```bash
sudo useradd --system --create-home --home-dir /opt/quickindex --shell /usr/sbin/nologin quickindex
sudo -u quickindex git clone <your-repo-url> /opt/quickindex/src       # or scp/rsync the folder
sudo -u quickindex python3 -m venv /opt/quickindex/venv
sudo -u quickindex /opt/quickindex/venv/bin/pip install --upgrade pip
sudo -u quickindex /opt/quickindex/venv/bin/pip install -r /opt/quickindex/src/backend/requirements.txt
```

Only `requirements.txt` is needed at runtime (`requirements-dev.txt` is for tests).

## 4. Configure secrets

```bash
sudo -u quickindex cp /opt/quickindex/src/backend/.env.production.example /opt/quickindex/.env.production
sudo chmod 600 /opt/quickindex/.env.production
sudo -u quickindex nano /opt/quickindex/.env.production
```

Values that must be changed (full list and comments are in `backend/.env.production.example`):

| Variable | Value |
| --- | --- |
| `APPWRITE_PROJECT_ID`, `APPWRITE_API_KEY`, `APPWRITE_DATABASE_ID` | from your Appwrite project (key: databases/tables/rows scopes only) |
| `FRONTEND_URL` | your Vercel custom domain, e.g. `https://app.example.com` |
| `CORS_ORIGINS` | the same origin(s), comma separated, no trailing slash |
| `PUBLIC_BASE_URL` | `https://api.example.com` |
| `INDEXNOW_KEY` | 8-128 letters/digits/dashes |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | optional; leave empty to keep Google off |
| `GOOGLE_REDIRECT_URI` | `https://api.example.com/api/v1/google/callback` (register the exact URI in Google Cloud) |
| `TOKEN_ENCRYPTION_KEY` | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Back it up: losing it forces every customer to reconnect Google |

Also add your app's hostname as a **Web platform** in Appwrite (Overview > Integrations > Platforms).

## 5. Run it with systemd

`/etc/systemd/system/quickindex-api.service`:

```ini
[Unit]
Description=QuickIndex API
After=network-online.target
Wants=network-online.target

[Service]
User=quickindex
Group=quickindex
WorkingDirectory=/opt/quickindex/src/backend
EnvironmentFile=/opt/quickindex/.env.production
Environment=PYTHONUNBUFFERED=1
# EXACTLY ONE worker. Do not raise --workers (see docs/DEPLOYMENT.md section 4).
# Caddy runs on the same machine, so only 127.0.0.1 is trusted for X-Forwarded-* headers. Never use '*'.
ExecStart=/opt/quickindex/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --timeout-graceful-shutdown 45
Restart=always
RestartSec=3
# Lets workers release their rows on stop; leftovers are recovered by the stale-row sweep (STALE_LOCK_SECONDS).
TimeoutStopSec=60
# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/quickindex

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now quickindex-api
sudo systemctl status quickindex-api
journalctl -u quickindex-api -f            # logs
curl -fsS http://127.0.0.1:8000/health/live
```

## 6. HTTPS with Caddy

`/etc/caddy/Caddyfile` (replace the domain; this is a trimmed version of the API block in the repo's `Caddyfile`):

```caddy
api.example.com {
	encode zstd gzip

	request_body {
		max_size 4MB
	}

	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "no-referrer"
		X-Frame-Options "DENY"
		Content-Security-Policy "default-src 'none'; frame-ancestors 'none'"
		-Server
	}

	reverse_proxy 127.0.0.1:8000 {
		health_uri /health/live
		health_interval 30s
	}
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl -fsS https://api.example.com/health/ready
```

Caddy gets the certificate on the first request; DNS must already point at the VPS.

## 7. Connect the Vercel frontend

In Vercel > Project > Settings > Environment Variables:

```
NEXT_PUBLIC_API_URL=https://api.example.com
NEXT_PUBLIC_APPWRITE_ENDPOINT=https://cloud.appwrite.io/v1
NEXT_PUBLIC_APPWRITE_PROJECT_ID=<your project id>
```

Redeploy (these are inlined at build time). Then confirm `CORS_ORIGINS` and `FRONTEND_URL` on the server match the exact Vercel domain
and restart: `sudo systemctl restart quickindex-api`.

## 8. Same settings on a PaaS (Railway / Render / Fly.io)

- Root/working directory: `backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers --forwarded-allow-ips '*'`
  (on a PaaS the platform's proxy is the only thing that can reach the process, so `*` is acceptable there; on a VPS exposed directly it is not)
- Health check path: `/health/live`
- Instances: **1**, always on (disable autoscaling and scale-to-zero)
- Put every variable from section 4 in the platform's environment settings, not in a file in the repo.
- Add your API custom domain on the platform, keeping it same-site with the frontend.

## 9. Updates and rollback

```bash
sudo -u quickindex git -C /opt/quickindex/src pull
sudo -u quickindex /opt/quickindex/venv/bin/pip install -r /opt/quickindex/src/backend/requirements.txt
sudo systemctl restart quickindex-api
curl -fsS https://api.example.com/health/ready
```

Expect a few seconds of unavailability. In-flight rows are released on SIGTERM or recovered after `STALE_LOCK_SECONDS`. To roll back,
`git checkout <previous-commit>`, reinstall requirements and restart.

## 10. Backups and operator scripts

Run from the backend directory with the production environment loaded:

```bash
cd /opt/quickindex/src/backend
sudo -u quickindex bash -c 'set -a; . /opt/quickindex/.env.production; set +a; /opt/quickindex/venv/bin/python scripts/backup_export.py --help'
```

Store archives off the server and test a restore into a separate Appwrite project before launch. See `docs/DEPLOYMENT.md` section 8.

## 11. Checklist

- [ ] `https://api.example.com/health/ready` returns 200 and shows worker heartbeats.
- [ ] `systemctl is-enabled quickindex-api` is `enabled` (survives reboot) and only one `uvicorn` process runs.
- [ ] `/opt/quickindex/.env.production` is mode 600 and not in git.
- [ ] Register, sign in, submit a URL and run a backlink check from the Vercel site.
- [ ] Google connect works (same-site domains, exact redirect URI registered, OAuth app out of "Testing").
- [ ] Egress to private ranges blocked at the firewall (`docs/DEPLOYMENT.md` section 7, adapt the iptables example to the host's interface instead of Docker's chain).
- [ ] `TOKEN_ENCRYPTION_KEY` and `BACKUP_ENCRYPTION_KEY` backed up separately.
