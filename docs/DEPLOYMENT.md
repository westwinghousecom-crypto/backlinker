# QuickIndex deployment runbook

Stack: **Caddy** (HTTPS) -> **web** (Next.js, standalone) and **api** (FastAPI + its background workers, one process).
**Appwrite Cloud is the only data service** (auth, database, job queue). No Redis, no other infrastructure.

> Status of this document: the Dockerfiles, `docker-compose.yml`, `Caddyfile`, CI workflow and the egress examples below were written and
> reviewed by reading, but **were not built, validated or run** in the environment that produced them (no Docker, Caddy or GitHub
> runner available). Treat the first staging deploy and the first CI run as the real validation.

## 0. Requirements

- A Linux host with Docker Engine + the Compose plugin, ports 80/443 (and 443/udp) open to the internet.
- **Two DNS names under the same registrable domain**, both pointing at the host: `app.example.com` (web) and `api.example.com` (API).
  They must be **same-site and HTTPS**: the Google sign-in cookie that binds an OAuth attempt to the starting browser is only sent
  to the API callback when both hosts are same-site.
- An Appwrite project with the tables from `backend/README.md`/`GOOGLE_SETUP.md` already created.

## 1. Appwrite platform settings

In the Appwrite console (Overview > Integrations > Platforms) add a **Web** platform for the hostname `app.example.com` (add `localhost`
only for development). Keep the server API key scoped to databases/tables/rows; it needs no users scope.

## 2. Configure

```
cp .env.production.example .env.production                    # domains + web build args: PUBLIC values only
cp backend/.env.production.example backend/.env.production    # API secrets: keep out of git, backed up elsewhere
```

Fill in `backend/.env.production` (Appwrite key, `INDEXNOW_KEY`, Google client, `TOKEN_ENCRYPTION_KEY`, `FRONTEND_URL`, `PUBLIC_BASE_URL`,
`CORS_ORIGINS`). Set `GOOGLE_REDIRECT_URI=https://api.example.com/api/v1/google/callback` and register that exact URI in Google Cloud.

**Secrets handling**
- Secrets exist in exactly one place at runtime: `backend/.env.production` (mode 600, owned by the deploy user), passed to the container
  with `env_file`. They are never baked into an image (`.dockerignore` excludes `.env*` and credential JSON files), never put in the web
  build arguments, and never committed (the root `.gitignore` excludes them).
- `TOKEN_ENCRYPTION_KEY`: back it up in a password manager. Losing it makes every stored Google token undecryptable (customers reconnect).
  To rotate, put the new key first and keep the old one after a comma until all connections have been re-saved.
- If your host has a secrets manager, inject the same variables from it instead of using the file.
- The Google client secret was shared in chat during development: rotate it before launch (add a new secret in Google Cloud, update the env, disable the old one).

## 3. Build and first deploy

The three `NEXT_PUBLIC_*` values are **inlined into the browser bundle when the web image is built**. Changing the API URL or Appwrite
project means rebuilding `web`.

```
docker compose --env-file .env.production config          # validate and view the resolved configuration
docker compose --env-file .env.production up -d --build
docker compose --env-file .env.production ps               # api and web should become "healthy", then proxy starts
curl -fsS https://api.example.com/health/live
curl -fsS https://api.example.com/health/ready
```

Caddy obtains certificates automatically on first request (DNS must already point at the host; keep the `caddy_data` volume).

## 4. Why exactly one API process

`api` runs `uvicorn --workers 1`. Do not scale it horizontally or raise `--workers`:
- The background workers (IndexNow, backlink checks, Google inspections) run inside the process and claim Appwrite rows with best-effort
  optimistic locking.
- API and recovery rate limits, and the per-minute Google quota window, are in memory.
- Only one Google inspection worker may run (`GSC_WORKER_COUNT=1`).
Scale by giving the one process more CPU/RAM. If you ever outgrow it, that is a design change (shared limiter + worker role split), not a flag.

## 5. Proxy flags and why

`--proxy-headers --forwarded-allow-ips <proxy IP>`: the API trusts `X-Forwarded-For`/`-Proto` only from Caddy's fixed address
(`PROXY_IP`, default `172.28.0.10`, set by compose). With `*`, any internet client could send its own `X-Forwarded-For` and bypass per-IP limits
(password recovery) or poison logs. `uvicorn` matches IPs, not container names, which is why the compose network has fixed addresses. If you
change `QI_SUBNET`/`PROXY_IP`, keep them consistent.

## 6. Deploying an update (single worker, minimal disruption)

```
git pull
docker compose --env-file .env.production build
docker compose --env-file .env.production up -d --no-deps api web     # recreates only what changed; proxy and certificates untouched
```

What happens to in-flight work: Docker sends **SIGTERM** to the old `api`; uvicorn stops accepting requests, workers stop claiming and
release the rows they hold, and the container has `stop_grace_period: 60s` to finish. Anything left in `processing` (a crash, a kill after the
grace period) is returned to the queue by the **stale-row recovery** (`STALE_LOCK_SECONDS`, default 300 s) after the new process starts. Rows
are never lost; a URL can occasionally be processed twice (IndexNow pings and fetches are idempotent). Expect API unavailability of a few
seconds during `up -d`; schedule deployments away from busy periods. To check afterwards: `/health/ready` must be 200 and show worker heartbeats.

Rollback: re-tag/rebuild the previous revision and run the same `up -d --no-deps` command.

## 7. Egress firewall for the api container (defence in depth)

The API already refuses private/loopback/link-local/reserved addresses in code (`app/core/safe_fetch.py`). Also block them at the network
level so a future bug cannot reach internal services or cloud metadata. **These rules are examples and were NOT tested here**; adapt to your
host/cloud and test that Appwrite, Google, IndexNow and the open web on 80/443 still work.

Docker host (iptables, applies to traffic from the compose network; use the `DOCKER-USER` chain):

```
SUBNET=172.28.0.0/24      # QI_SUBNET
for NET in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10; do
  iptables -I DOCKER-USER -s $SUBNET -d $NET -j DROP
done
# but allow replies inside the compose network itself (proxy <-> api <-> web) BEFORE the drops:
iptables -I DOCKER-USER -s $SUBNET -d $SUBNET -j ACCEPT
```

nftables equivalent (add to a forward-hook chain):

```
ip saddr 172.28.0.0/24 ip daddr 172.28.0.0/24 accept
ip saddr 172.28.0.0/24 ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 100.64.0.0/10 } drop
```

Add the IPv6 equivalents (`fc00::/7`, `fe80::/10`, `::1`) if the host has IPv6. On a cloud VM also disable or restrict the instance
metadata service (for example require IMDSv2) and use security groups that deny RFC1918 egress from the API workload.

## 8. Backups and restore

Back up the Appwrite data you cannot recreate (customer batches, results, Google connections/history, feed opt-ins). The backup tooling lives in
`backend/scripts/`:

- `scripts/backup_export.py`: exports the tables to an (optionally encrypted) archive.
- `scripts/restore_backup.py`: restores from such an archive.

Run them inside the image so they use the production credentials:

```
docker compose --env-file .env.production exec api python scripts/backup_export.py --help
docker compose --env-file .env.production exec api python scripts/restore_backup.py --help
```

Store archives off the host. **An export that has never been restored is not a backup**: do a test restore into a separate Appwrite project
(set `APPWRITE_PROJECT_ID`/`APPWRITE_API_KEY` to the staging project) before launch and after every schema change. Keep `TOKEN_ENCRYPTION_KEY`
backed up separately: restored Google connections are useless without it. Refer to the other fork's documentation of those scripts for exact
options (names above are the agreed script names; confirm their flags).

## 9. CI

`.github/workflows/ci.yml` runs on pushes to `main` and every pull request: backend tests, frontend tests + typecheck + lint + build, Docker
image builds (not pushed), and dependency/secret scans. Dependabot (`.github/dependabot.yml`) opens weekly update PRs for pip, npm, Docker and
GitHub Actions. Pin actions to commit SHAs if you need stricter supply-chain guarantees.

## 10. Checklist before pointing real customers at it

- [ ] `docker compose config` clean; `ps` shows api, web, proxy healthy.
- [ ] `https://api.example.com/health/ready` is 200; a worker heartbeat is shown for each worker type.
- [ ] Browser console shows no Content-Security-Policy violations on login, dashboard, backlinks and Google pages (the CSP is conservative and
      unverified).
- [ ] Register, sign in, submit a URL, run a backlink check end to end on the staging host.
- [ ] Google: connect, inspect, disconnect (see `backend/GOOGLE_SETUP.md`); OAuth app moved out of "Testing".
- [ ] Egress rules applied and verified; secrets file permissions checked; test restore completed.


## Testing the Docker stack locally with Colima (macOS or Linux)

[Colima](https://github.com/abiosoft/colima) is a lightweight container runtime for **macOS and Linux**. It provides a Docker-compatible engine, so the
Dockerfiles, `docker-compose.yml` and `scripts/docker-smoke.sh` in this repository work with it unchanged. It does **not** run on Windows: on
Windows use WSL2 with Docker Engine inside it (this needs CPU virtualization enabled in the BIOS), or run the CI workflow on a Linux runner.

```bash
brew install colima docker docker-compose      # macOS (Homebrew). On Linux use your package manager or the Colima release binary.
colima start --cpu 2 --memory 4 --disk 20      # starts the VM and points the docker CLI at it
docker info                                    # should print the Colima engine

bash scripts/docker-smoke.sh                   # builds both images and checks the stack (about 5 to 10 minutes the first time)
colima stop                                    # when you are done
```

What the smoke test verifies: both images build (including the build-time `NEXT_PUBLIC_*` arguments), both run as non-root, no `.env` and no dev
dependencies are in the images, the API runs exactly one uvicorn process that trusts only the proxy IP, the root filesystem is read-only, only the
proxy publishes ports, `/health/live` is 200 and `/health/ready` is 503 when Appwrite is unreachable, protected routes return 401, HSTS is sent, and
`SIGTERM` stops the API inside the grace period. It uses `app.localhost` / `api.localhost` (Caddy issues local certificates for them) and fake secrets only.

Colima notes: on Apple Silicon the images build for `arm64` (all base images publish it). If a build runs out of memory, restart with
`colima start --memory 6`. Ports 80 and 443 are forwarded by Colima; if they are taken on your machine, stop the other service first.
**This procedure has not been executed by the author**, because the authoring machine is Windows without a container runtime. The first real run
may reveal problems in the Docker files; treat any failure as a bug to fix in the files, not in the checks.
