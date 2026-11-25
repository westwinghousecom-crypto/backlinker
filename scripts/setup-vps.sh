#!/usr/bin/env bash
# One-shot backend setup for an Ubuntu/Debian VPS (e.g. Hostinger VPS). Run as root:
#   bash setup-vps.sh api.example.com https://github.com/you/repo.git
# Untested: review it, run on staging first. Guide: docs/BACKEND_DEPLOY_NO_DOCKER.md
set -euo pipefail

API_DOMAIN="${1:?usage: setup-vps.sh <api-domain> <git-repo-url>}"
REPO_URL="${2:?usage: setup-vps.sh <api-domain> <git-repo-url>}"
BASE=/opt/quickindex

apt-get update
apt-get install -y python3 python3-venv python3-pip git ufw curl caddy

ufw allow OpenSSH
ufw allow 80,443/tcp
ufw --force enable

id quickindex >/dev/null 2>&1 || useradd --system --create-home --home-dir "$BASE" --shell /usr/sbin/nologin quickindex
if [ -d "$BASE/src/.git" ]; then
  sudo -u quickindex git -C "$BASE/src" pull
else
  sudo -u quickindex git clone "$REPO_URL" "$BASE/src"
fi
[ -d "$BASE/venv" ] || sudo -u quickindex python3 -m venv "$BASE/venv"
sudo -u quickindex "$BASE/venv/bin/pip" install --upgrade pip
sudo -u quickindex "$BASE/venv/bin/pip" install -r "$BASE/src/backend/requirements.txt"

if [ ! -f "$BASE/.env.production" ]; then
  cp "$BASE/src/backend/.env.production.example" "$BASE/.env.production"
  chown quickindex:quickindex "$BASE/.env.production"
  chmod 600 "$BASE/.env.production"
  echo ">>> Edit $BASE/.env.production now (Appwrite keys, INDEXNOW_KEY, FRONTEND_URL, CORS_ORIGINS, PUBLIC_BASE_URL),"
  echo ">>> then run:  systemctl restart quickindex-api"
fi

cat > /etc/systemd/system/quickindex-api.service <<EOF
[Unit]
Description=QuickIndex API
After=network-online.target
Wants=network-online.target

[Service]
User=quickindex
Group=quickindex
WorkingDirectory=$BASE/src/backend
EnvironmentFile=$BASE/.env.production
Environment=PYTHONUNBUFFERED=1
ExecStart=$BASE/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --timeout-graceful-shutdown 45
Restart=always
RestartSec=3
TimeoutStopSec=60
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$BASE

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/caddy/Caddyfile <<EOF
$API_DOMAIN {
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
EOF

systemctl daemon-reload
systemctl enable --now quickindex-api
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

echo "Done. Check: curl -fsS https://$API_DOMAIN/health/ready  (after editing .env.production and restarting the service)"
