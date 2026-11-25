#!/usr/bin/env bash
# Smoke test for the QuickIndex Docker stack. Works with any Docker-compatible runtime, including Colima (macOS/Linux).
#
#   colima start --cpu 2 --memory 4 --disk 20      # once
#   bash scripts/docker-smoke.sh
#
# It builds both images with PLACEHOLDER public settings, starts the stack with fake secrets, and checks the things the
# Dockerfiles and compose file promise. It never uses real credentials and tears everything down at the end.
#
# NOT RUN in the environment that wrote it (no container runtime there). If a check fails, that is a real finding: fix the
# Docker files, do not edit the check.
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
ok()   { echo "PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "FAIL  $1"; FAIL=$((FAIL+1)); }
check() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }

command -v docker >/dev/null || { echo "docker CLI not found. With Colima: brew install colima docker docker-compose && colima start"; exit 2; }
docker info >/dev/null 2>&1 || { echo "No running container engine. Start one (for example: colima start)."; exit 2; }
echo "engine: $(docker info --format '{{.Name}} / {{.OperatingSystem}} / {{.Architecture}}')"

TMP="$(mktemp -d)"; trap 'docker compose --env-file "$TMP/root.env" -p qi_smoke down -v --remove-orphans >/dev/null 2>&1 || true; rm -rf "$TMP"' EXIT
KEY="$(python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"

cat > "$TMP/root.env" <<EOF
APP_DOMAIN=app.localhost
API_DOMAIN=api.localhost
ACME_EMAIL=ops@example.com
NEXT_PUBLIC_API_URL=https://api.localhost
NEXT_PUBLIC_APPWRITE_ENDPOINT=https://cloud.appwrite.io/v1
NEXT_PUBLIC_APPWRITE_PROJECT_ID=smoke-test-project
EOF
# Fake API settings: Appwrite is unreachable on purpose, so /health/ready must say 503 while /health/live says 200.
cp backend/.env.production.example backend/.env.production
sed -i.bak -E "s|^TOKEN_ENCRYPTION_KEY=.*|TOKEN_ENCRYPTION_KEY=${KEY}|; s|^BACKUP_ENCRYPTION_KEY=.*|BACKUP_ENCRYPTION_KEY=${KEY}|; s|^APPWRITE_PROJECT_ID=.*|APPWRITE_PROJECT_ID=smoke|; s|^APPWRITE_API_KEY=.*|APPWRITE_API_KEY=smoke|; s|^APPWRITE_DATABASE_ID=.*|APPWRITE_DATABASE_ID=smoke|" backend/.env.production 2>/dev/null || true
rm -f backend/.env.production.bak
trap 'rm -f backend/.env.production; docker compose --env-file "$TMP/root.env" -p qi_smoke down -v --remove-orphans >/dev/null 2>&1 || true; rm -rf "$TMP"' EXIT
C="docker compose --env-file $TMP/root.env -p qi_smoke"

check "compose file is valid" "$C config -q"
echo "--- building (first run takes several minutes) ..."
check "API image builds"  "$C build api"
check "web image builds (NEXT_PUBLIC_* build args)" "$C build web"

check "API image runs as a non-root user" '[ "$(docker run --rm --entrypoint id quickindex-api:latest -u)" != "0" ]'
check "web image runs as a non-root user" '[ "$(docker run --rm --entrypoint id quickindex-web:latest -u)" != "0" ]'
check "no .env file inside the API image" '! docker run --rm --entrypoint sh quickindex-api:latest -c "ls /app/.env* 2>/dev/null | grep -q ."'
check "API image has no test or dev dependencies" '! docker run --rm --entrypoint python quickindex-api:latest -c "import pytest" 2>/dev/null'
check "web image has no devDependencies (typescript absent)" '! docker run --rm --entrypoint sh quickindex-web:latest -c "ls node_modules/typescript 2>/dev/null | grep -q ."'
check "NEXT_PUBLIC_API_URL is inlined into the web bundle" \
  'docker run --rm --entrypoint sh quickindex-web:latest -c "grep -rl https://api.localhost .next/static | head -1 | grep -q ."'

echo "--- starting the stack ..."
$C up -d
for i in $(seq 1 40); do
  S="$($C ps --format '{{.Service}}={{.Health}}' 2>/dev/null | tr '\n' ' ')"
  echo "$S" | grep -q "api=healthy" && echo "$S" | grep -q "web=healthy" && break
  sleep 3
done
check "api container is healthy (liveness)" "echo '$S' | grep -q 'api=healthy'"
check "web container is healthy"            "echo '$S' | grep -q 'web=healthy'"

check "only the proxy publishes host ports" \
  '[ -z "$(docker ps --filter label=com.docker.compose.project=qi_smoke --format "{{.Names}} {{.Ports}}" | grep -E "api|web" | grep -E "0\.0\.0\.0|:::" )" ]'
check "api root filesystem is read-only" '[ "$(docker inspect -f "{{.HostConfig.ReadonlyRootfs}}" "$($C ps -q api)")" = "true" ]'
check "api drops all capabilities"       'docker inspect -f "{{.HostConfig.CapDrop}}" "$($C ps -q api)" | grep -qi all'
check "api runs EXACTLY ONE uvicorn process" '[ "$(docker exec "$($C ps -q api)" sh -c "ps -eo args | grep -c \"[u]vicorn app.main\"")" = "1" ]'
check "uvicorn trusts only the proxy IP (not *)" \
  '! docker exec "$($C ps -q api)" sh -c "ps -eo args | grep -F -- \"--forwarded-allow-ips *\""'

echo "--- through the proxy (self-signed local certificate, hence -k) ..."
R="--resolve api.localhost:443:127.0.0.1 --resolve app.localhost:443:127.0.0.1 -k -s -o /dev/null -w %{http_code}"
check "GET https://api.localhost/health/live is 200"  '[ "$(curl $R https://api.localhost/health/live)" = "200" ]'
check "GET https://api.localhost/health/ready is 503 while Appwrite is unreachable (fake credentials)" '[ "$(curl $R https://api.localhost/health/ready)" = "503" ]'
check "protected API route needs sign-in (401)"       '[ "$(curl $R https://api.localhost/api/v1/check-batches)" = "401" ]'
check "web app serves the login page (200)"           '[ "$(curl $R https://app.localhost/login)" = "200" ]'
check "HSTS header is present" 'curl --resolve app.localhost:443:127.0.0.1 -k -sI https://app.localhost/login | grep -qi strict-transport-security'
check "SIGTERM stops the API within the grace period (graceful shutdown)" \
  'start=$(date +%s); $C stop -t 60 api >/dev/null; [ $(( $(date +%s) - start )) -lt 55 ]'

echo; echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
