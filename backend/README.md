# QuickIndex Backend

FastAPI service for bulk backlink indexing. URLs are stored in Appwrite (TablesDB) and
background workers submit them to IndexNow.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill in values
uvicorn app.main:app --reload
```

## Appwrite table

Create a database and a table (default id urls) with these columns:

| Column     | Type    | Required | Notes                                          |
|------------|---------|----------|------------------------------------------------|
| batch_id   | string  | yes      | uuid, size 64                                  |
| user_id    | string  | yes      | size 64                                        |
| url        | string  | yes      | size 2048                                      |
| status     | string  | yes      | pending / processing / submitted / completed / failed      |
| attempts   | integer | yes      | default 0                                      |
| locked_by  | string  | no       | nullable, size 64                              |

Recommended: index on status. The API key needs 
ows.read and 
ows.write scopes.

## API

- POST /api/v1/submit body {"urls": ["https://..."]} (1..1000 URLs)
  -> {"batch_id": "...", "total": N}
- POST /api/v1/submit-one body {"url": "https://..."} -> same response
- GET /api/v1/batches/{batch_id} -> per-status counts, `done` flag and per-URL status
- GET /sitemap.xml, /feed.xml (all completed URLs); /batches/{batch_id}/sitemap.xml and /feed.xml (one batch)
- GET /robots.txt (points crawlers at the sitemap); GET /<INDEXNOW_KEY>.txt (IndexNow ownership proof)
- GET /health

Rows stuck in `processing` longer than STALE_LOCK_SECONDS are recovered.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest
```

## Notes

- Workers claim rows with optimistic locking (update then re-read). It is best effort, not atomic.
- Set USE_PROXY=true to route pings through free proxies (falls back to direct requests).
- Host your IndexNow key file at https://<your-site>/<INDEXNOW_KEY>.txt for IndexNow to accept submissions.

## Discovery channels

- **IndexNow (bulk):** URLs are grouped by host and POSTed in one request per host (up to 10,000), with fallback endpoints.
  IndexNow only accepts URLs on a host that serves your key file, so it works for your own domains, not arbitrary third-party pages.
- **Feed ping:** `PING_ENDPOINTS` (default Ping-O-Matic) get an XML-RPC `weblogUpdates.ping` for `/feed.xml` whenever new URLs
  are published, at most every `PING_INTERVAL_SECONDS`. Disabled while `PUBLIC_BASE_URL` is localhost.
- **Wayback Machine:** set `WAYBACK_SAVE=true` to also request a snapshot of each URL (rate limited by the Archive).
- IndexNow HTTP 200 marks a URL `completed`; HTTP 202 (received, key validation pending) marks it `submitted`. Both stop retries.
  The Wayback save counts as `completed`. Rate-limited or rejected URLs are retried, then `failed`.

## URL checker

`POST /api/v1/check` with `{"urls": [...up to 50], "target": "https://your-site.com"}` fetches each page and reports whether
Google can index it: HTTP status, redirects, robots.txt (Googlebot), noindex (meta tag or header), canonical, and whether the
page really links to `target` (and whether that link is nofollow/ugc/sponsored). Verdict: eligible / warning / blocked / unreachable.
Private and internal addresses are refused.

## Important limits

- Google only trusts a sitemap for URLs on the sitemap's own host or a Search Console-verified property. `/sitemap.xml` and
  `/feed.xml` list third-party URLs, so treat them as a weak discovery hint, not an indexing request.
- `completed`/`submitted` mean a search-engine endpoint accepted the notification. They are not proof of Google indexing.

## Check My Backlinks (saved batches)

Tables (create in Appwrite): `check_batches` (user_id, target, total) and `checks` (batch_id, user_id, position, url, target, status,
attempts, locked_by, verdict, result[mediumtext JSON]) with indexes on `batch_id` and `status`.

- `POST /api/v1/check-batches` `{urls[1..1000], target?}` -> `{batch_id, total}`; background workers (`CHECK_WORKER_COUNT`) do the checks
- `GET /api/v1/check-batches/{id}` -> summary + one item per URL (state, full result with plain-English problems and fixes)
- `GET /api/v1/check-batches` -> the signed-in customer's batch history
- `DELETE /api/v1/check-batches/{id}` -> delete a batch and its results
- `POST /api/v1/check-batches/{id}/checks/{check_id}/recheck` -> queue one URL again
- `PUT /api/v1/check-batches/{id}/sharing` `{public_report}` -> owner's opt-in for a read-only, no-sign-in link to this batch's
  results (e.g. to show a client); `GET /api/v1/check-batches/{id}/sharing` reads the current state. Off by default.
- `GET /api/v1/check-batches/{id}/public` -> the same summary + items, but **no sign-in required**; 404 (identical either way)
  if the batch does not exist or was never shared. Strips the owner's private "I searched Google myself" notes.
- `google_index_status` is always `"unknown"`: technical checks cannot prove indexing.
- QuickIndex accepts up to **1,000 URLs** per check or submit batch (`{urls[1..1000]}` above) — well above the roughly 500 some
  competing indexing tools cap a single submission at.


## Authentication and data isolation

- Customers sign up / sign in with **Appwrite Auth** in the browser. The browser sends a short-lived Appwrite JWT as
  `Authorization: Bearer <jwt>`; the API verifies it with Appwrite (`GET /account`) and uses the verified user id.
  **No endpoint accepts a user id from the client.** Every endpoint except `/health`, `robots.txt`, the IndexNow key file and
  the per-batch public feeds requires sign-in (401 otherwise).
- Every read/update/delete is scoped to the verified owner in the service layer (and again in the Appwrite query). Someone
  else's batch looks exactly like a batch that does not exist (404).
- Tables use Appwrite **row security** (`rowSecurity: true`, no table-level permissions); each row is created with
  `read("user:<owner>")` only. **The API's admin key bypasses row security**, so isolation in this API depends on the owner
  checks above (covered by `tests/test_authorization.py`). Give the API key only the `databases/tables/rows` scopes: it does not need any users scope.
- Per-customer limits: `RATE_LIMIT_PER_MINUTE` (writes) and `MAX_QUEUED_PER_USER` (URLs/checks waiting in the queue).
- `PUBLIC_GLOBAL_FEED=false` (default): there is no public page listing every customer's URLs. Per-batch feeds
  (`/batches/<id>/feed.xml`) remain public by design (the batch id is an unguessable capability link).
- Register your web app's hostname in Appwrite (Overview > Integrations > Platforms) for each domain you deploy to.

## Outbound request safety (SSRF / DNS rebinding)

All fetching of customer-supplied URLs goes through `app/core/safe_fetch.py`:
the DNS resolver itself refuses non-public addresses (IPv4, IPv6, IPv4-mapped, 6to4, NAT64, link-local, loopback, private,
reserved, multicast), so the address that was checked is the address connected to; DNS caching is off; IP-literal URLs are
checked directly; every redirect hop is re-validated; only http/https on ports 80/443, no credentials in URLs; max 5 redirects,
1 MB per page, 30 s total; TLS certificates are verified; environment proxies are ignored.

**Also apply network-level egress rules in production** (not configured by this repo; adapt to your host):

- Run the API in a network where outbound traffic to RFC1918 ranges, `169.254.0.0/16` (cloud metadata), `100.64.0.0/10`, `127.0.0.0/8`,
  `fc00::/7`, `fe80::/10` and your database/admin networks is denied, while Appwrite, IndexNow endpoints and the public internet on 80/443 are allowed.
- On Linux with nftables, for example: `nft add rule inet filter output ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 100.64.0.0/10 } drop`
  (plus the IPv6 equivalents), or the equivalent security-group/egress policy of your cloud or container platform.
- Require IMDSv2 / disable the metadata service for this workload if your cloud allows it.

## Bulk inserts

Submissions and checks are written with Appwrite TablesDB bulk create (`create_rows`) in chunks of `APPWRITE_BULK_CHUNK_SIZE`
(**100 on the Free plan, 1000 on Pro**). Row ids are deterministic (`batch uuid prefix + position`), so if a bulk request fails the
chunk is retried row by row and rows that already exist (HTTP 409) are counted, not duplicated. Batch deletion uses bulk delete.


## Account security, Google Search Console

- **Password recovery / email verification:** `POST /api/v1/account/recovery` always answers 202 with the same text (no account enumeration),
  with per-IP and per-address limits and a response-time floor; links in the emails use `FRONTEND_URL`, never the request host.
  `POST /api/v1/account/verification` (signed in) resends the verification email (60 s cooldown, 5 per hour).
- **Per-batch feeds are private by default.** The owner reads them with sign-in at `GET /api/v1/batches/{id}/feed.xml` and `/sitemap.xml`;
  the public `/batches/{id}/feed.xml` exists only after the owner opts in with `PUT /api/v1/batches/{id}/sharing {"public_feed": true}`.
  The global feed stays off (`PUBLIC_GLOBAL_FEED=false`).
- **Google Search Console:** see [GOOGLE_SETUP.md](GOOGLE_SETUP.md). Endpoints under `/api/v1/google/` (status, connect, callback, connection,
  properties, property, targets, targets/{id}/history|recheck, sitemaps). A page is shown as Confirmed Indexed / Confirmed Not Indexed ONLY from
  Google's own URL Inspection verdict (PASS = indexed; FAIL and NEUTRAL = not indexed; anything else = Unknown). HTTP checks, IndexNow, WebSub,
  sitemaps and social shares never produce those statuses. Inspections run now and at 1, 3, 7 and 14 days (stopping once Google confirms indexing),
  within Google's 2,000/day and 600/minute per-property quota.
- Appwrite tables for these features: `google_connections`, `gsc_targets`, `gsc_history`, `google_quota`, `batch_sharing`.
- **OAuth hardening:** the Google sign-in `state` is sealed, expires in 10 minutes, is single-use (consumed in Appwrite, table `google_oauth_states`) and is accepted only
  from the browser that started the flow (HttpOnly cookie bound to the state). `DELETE /api/v1/google/data` disconnects and erases a customer's tracked URLs and history.


## Appwrite usage: workers sleep until woken

Appwrite meters database reads and writes (Free: 500,000 reads and 250,000 writes per month). The queue workers used to poll Appwrite every
second or so even with nothing queued, which cost about **690,000 read requests per 30 days for an idle server**. They now sleep until the code
that creates work wakes them (`app/core/wakeup.py`: submit, check batch, recheck, Google URL added), and otherwise poll only every
`WORKER_FALLBACK_POLL_SECONDS` (default 240, minimum 60).

Nothing is lost: rows that were already `pending` when the process starts are found by the first poll; a wake-up that arrives while a worker is busy is
remembered; rows left `processing` by a crash are recovered on the next wake-up; a graceful shutdown releases claimed rows. The cost of the safety net is
latency, not correctness: work created by another process, scheduled Google rechecks and retry times are picked up within about the fallback interval.
Measure it yourself with `python scripts/measure_usage.py 700` (real Appwrite, idle, with exact request counts) or read `appwrite_requests` in `GET /health/ready`.

## Health endpoints

- `GET /health/live`: the process is up (no dependencies).
- `GET /health/ready`: 200 only if Appwrite is reachable (cached 5 minutes, so monitoring costs almost no reads) AND every expected worker
  (`WORKER_COUNT`, `CHECK_WORKER_COUNT`, and the Google worker when Google is configured) has reported a recent heartbeat. 503 otherwise, with the per-worker state.
  Workers get 90 seconds after start to report. Point container health checks at `/health/live` and uptime/alerting at `/health/ready`.

## Data lifecycle: retention, export, deletion, backups

- **Retention** (`app/features/retention`): once a day (first run 5 minutes after start) old rows are bulk-deleted: check batches and results
  (`RETENTION_CHECK_BATCH_DAYS`=90), finished submissions and their public-feed flag (`RETENTION_SUBMISSION_DAYS`=90), Google inspection history
  (`RETENTION_GSC_HISTORY_DAYS`=365), consumed OAuth states (`RETENTION_OAUTH_STATE_HOURS`=1) and quota counters (`RETENTION_QUOTA_DAYS`=7).
  Pending/processing submissions and tracked Google URLs are never deleted. An idle run costs 7 Appwrite write requests and 0 reads.
  The privacy policy states these periods; a frontend test fails if they drift apart.
- **Export / deletion:** `GET /api/v1/account/export` (3 per hour; never includes the Google refresh token) and `DELETE /api/v1/account` with `{"confirm":"DELETE"}`:
  revokes Google, erases every row the customer owns, then removes the Appwrite user. Needs the API key's `users.write` scope to delete the user record; without it
  the account is blocked using the customer's own session and the record must be removed in the console. (Least privilege: the key does not need `users.read`.)
- **Backups:** `scripts/backup_export.py` writes `backups/quickindex-YYYYMMDD-HHMMSS.json.enc` (Fernet-encrypted with `BACKUP_ENCRYPTION_KEY`) plus a manifest
  (row counts + SHA-256). `scripts/restore_backup.py FILE --verify | --dry-run | --restore [--force]`. Rows changed after the backup are kept unless `--force`.
  A full restore needs BOTH `BACKUP_ENCRYPTION_KEY` and `TOKEN_ENCRYPTION_KEY` (Google tokens inside the backup stay encrypted with the latter). `backups/` is git-ignored.
  Run the export on a schedule you choose (for example nightly via Task Scheduler/cron) and store the files and the key in different places. Test `--verify` regularly.
- **Legal drafts:** `docs/legal/*.md` (also served at `/privacy` and `/terms` with a DRAFT banner); edit the markdown then run `npm run sync:legal` in `frontend`.
