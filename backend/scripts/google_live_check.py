"""Operator tool for validating QuickIndex's Google Search Console integration against Google's REAL API.

Run from the backend folder (credentials are read ONLY from backend/.env, never from arguments or the frontend):

    .venv\\Scripts\\python scripts\\google_live_check.py preflight
    .venv\\Scripts\\python scripts\\google_live_check.py --user-id <id> status
    .venv\\Scripts\\python scripts\\google_live_check.py --user-id <id> properties
    .venv\\Scripts\\python scripts\\google_live_check.py --user-id <id> inspect <url> [<url> ...]
    .venv\\Scripts\\python scripts\\google_live_check.py --user-id <id> sitemaps
    .venv\\Scripts\\python scripts\\google_live_check.py --user-id <id> refresh
    .venv\\Scripts\\python scripts\\google_live_check.py --user-id <id> schedule <url>
    .venv\\Scripts\\python scripts\\google_live_check.py --user-id <id> disconnect
    .venv\\Scripts\\python scripts\\google_live_check.py --user-id <id> delete-data

The consent step itself (signing in to Google) happens in the QuickIndex web app, in your own browser. This tool works
with the connection that step stores. Everything printed is passed through `redact`: tokens and secrets are masked and
email addresses are shortened. Nothing here fabricates a response: every "raw" block is what Google returned.
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402

SECRET_KEYS = {"access_token", "refresh_token", "id_token", "client_secret", "code", "authorization", "code_verifier", "token"}
TOKENISH = re.compile(r"(ya29\.[\w.-]+|1//[\w.-]{10,}|GOCSPX-[\w-]+|eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]*)")
EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def redact(value):
    """Mask credentials and shorten email addresses in anything we are about to print."""
    if isinstance(value, dict):
        return {k: ("[redacted]" if k.lower() in SECRET_KEYS and v else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return EMAIL.sub(r"\1***@\2", TOKENISH.sub("[redacted]", value))
    return value


def show(title: str, data) -> None:
    print(f"\n--- {title}")
    print(json.dumps(redact(data), indent=2, default=str) if not isinstance(data, str) else redact(data))


# ---------------------------------------------------------------------------------------------- preflight

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
CLIENT_ID = re.compile(r"^\d+-[a-z0-9]+\.apps\.googleusercontent\.com$")
REQUIRED_TABLES = ["urls", "checks", "check_batches", "batch_sharing", "google_connections", "gsc_targets", "gsc_history",
                   "google_quota", "google_oauth_states"]


def _site(host: str) -> str:
    parts = host.split(".")
    return host if host in ("localhost", "127.0.0.1") or len(parts) < 2 else ".".join(parts[-2:])


def check_config() -> list[tuple[str, str, str]]:
    """Static checks of the environment. Never prints a secret value."""
    s = get_settings()
    out: list[tuple[str, str, str]] = []
    add = lambda status, name, msg: out.append((status, name, msg))  # noqa: E731

    add(PASS if CLIENT_ID.match(s.GOOGLE_CLIENT_ID) else FAIL, "GOOGLE_CLIENT_ID",
        "looks like a Google web client id" if CLIENT_ID.match(s.GOOGLE_CLIENT_ID)
        else "missing or not in the form 123456-abc.apps.googleusercontent.com")
    if not s.GOOGLE_CLIENT_SECRET:
        add(FAIL, "GOOGLE_CLIENT_SECRET", "missing")
    elif not s.GOOGLE_CLIENT_SECRET.startswith("GOCSPX-"):
        add(WARN, "GOOGLE_CLIENT_SECRET", f"set ({len(s.GOOGLE_CLIENT_SECRET)} chars) but does not start with GOCSPX- (older clients differ)")
    else:
        add(PASS, "GOOGLE_CLIENT_SECRET", f"set ({len(s.GOOGLE_CLIENT_SECRET)} chars)")
    try:
        from app.features.google import crypto

        crypto.encrypt_token("preflight", "x")
        add(PASS, "TOKEN_ENCRYPTION_KEY", "valid Fernet key (refresh tokens can be encrypted)")
    except Exception as e:
        add(FAIL, "TOKEN_ENCRYPTION_KEY", f"missing or invalid ({type(e).__name__})")

    u = urlsplit(s.GOOGLE_REDIRECT_URI)
    local = u.hostname in ("localhost", "127.0.0.1")
    path_ok = u.path == "/api/v1/google/callback"
    add(PASS if path_ok else FAIL, "GOOGLE_REDIRECT_URI path", u.path if path_ok else f"{u.path!r} must be exactly /api/v1/google/callback")
    add(PASS if (u.scheme == "https" or local) else FAIL, "GOOGLE_REDIRECT_URI scheme",
        "https (or localhost development)" if (u.scheme == "https" or local) else "Google requires https for non-localhost redirect URIs")
    f = urlsplit(s.FRONTEND_URL)
    same = _site(f.hostname or "") == _site(u.hostname or "")
    add(PASS if same else FAIL, "same-site hosting", "app and API are same-site, so the sign-in binding cookie will be sent" if same
        else f"{f.hostname} and {u.hostname} are not same-site: the binding cookie would not reach the callback")
    add(PASS if s.GSC_WORKER_COUNT == 1 else WARN, "GSC_WORKER_COUNT", f"{s.GSC_WORKER_COUNT} (use exactly 1: the per-minute limiter is in memory)")
    add(PASS if (s.GSC_INSPECT_PER_DAY <= 2000 and s.GSC_INSPECT_PER_MINUTE <= 600) else FAIL, "quota limits",
        f"{s.GSC_INSPECT_PER_DAY}/day, {s.GSC_INSPECT_PER_MINUTE}/minute (Google: 2000/day, 600/minute per property)")
    return out


async def check_appwrite() -> list[tuple[str, str, str]]:
    from appwrite.query import Query

    from app.core.appwrite_client import get_tables_db

    s, out = get_settings(), []
    db = get_tables_db()
    for t in REQUIRED_TABLES:
        try:
            await asyncio.to_thread(db.list_rows, database_id=s.APPWRITE_DATABASE_ID, table_id=t, queries=[Query.limit(1)])
            out.append((PASS, f"Appwrite table {t}", "exists"))
        except Exception as e:
            out.append((FAIL, f"Appwrite table {t}", f"not reachable ({getattr(e, 'code', type(e).__name__)})"))
    return out


async def check_google_network() -> list[tuple[str, str, str]]:
    """Live (but credential-free) reachability, then a credential check Google itself answers."""
    from app.core.safe_fetch import make_session
    from app.features.google import api

    s, out = get_settings(), []
    try:
        async with make_session() as sess:
            async with sess.get("https://accounts.google.com/.well-known/openid-configuration") as r:
                out.append((PASS if r.status == 200 else FAIL, "Google reachable (live)", f"accounts.google.com HTTP {r.status}"))
    except Exception as e:
        out.append((FAIL, "Google reachable (live)", type(e).__name__))
        return out
    if not (CLIENT_ID.match(s.GOOGLE_CLIENT_ID) and s.GOOGLE_CLIENT_SECRET):
        out.append((WARN, "Google accepts the client (live)", "skipped: client id/secret not set"))
        return out
    # An obviously invalid authorization code: a valid client gets "invalid_grant", a wrong id/secret gets "invalid_client".
    try:
        await api.call("POST", api.TOKEN_URL, data={"client_id": s.GOOGLE_CLIENT_ID, "client_secret": s.GOOGLE_CLIENT_SECRET,
                                                    "code": "preflight-not-a-real-code", "grant_type": "authorization_code",
                                                    "redirect_uri": s.GOOGLE_REDIRECT_URI, "code_verifier": "x" * 64})
        out.append((WARN, "Google accepts the client (live)", "unexpected success"))
    except api.GoogleApiError as e:
        if e.code == "invalid_grant":
            out.append((PASS, "Google accepts the client (live)", "token endpoint answered invalid_grant: client id and secret are valid"))
        elif e.code == "invalid_client":
            out.append((FAIL, "Google accepts the client (live)", "invalid_client: wrong client id or secret"))
        elif e.code == "redirect_uri_mismatch":
            out.append((FAIL, "Google accepts the client (live)", "redirect_uri_mismatch: register the exact callback URI"))
        else:
            out.append((WARN, "Google accepts the client (live)", f"{e.kind} {e.status} {e.code}"))
    return out


def print_report(rows: list[tuple[str, str, str]]) -> int:
    for status, name, msg in rows:
        print(f"{status:4}  {name}: {redact(msg)}")
    failed = [r for r in rows if r[0] == FAIL]
    print(f"\n{len(rows) - len(failed)} of {len(rows)} checks without FAIL" + (" -> NOT ready for live testing" if failed else " -> ready for live testing"))
    return 1 if failed else 0


async def preflight() -> int:
    rows = check_config() + await check_appwrite() + await check_google_network()
    return print_report(rows)


# ---------------------------------------------------------------------------------------------- live commands

async def _conn(user_id: str):
    from app.features.google import repository as repo

    row = await repo.get_connection(user_id)
    if not row:
        sys.exit("No Google connection stored for that user. Connect in the web app first (Google Index Status > Connect).")
    return row


async def cmd_status(user_id: str) -> int:
    from app.features.google import service

    show("status (what the dashboard reads)", await service.get_status(user_id))
    return 0


async def cmd_properties(user_id: str) -> int:
    from app.features.google import api, service

    row = await _conn(user_id)
    token = await service.access_token_for(user_id, row)
    show("RAW Google response: GET /webmasters/v3/sites", {"siteEntry": await api.list_sites(token)})
    show("as QuickIndex classifies them", [p.as_dict() for p in await service.list_properties(user_id)])
    print("\nselected property:", redact(row.get("selected_property")))
    return 0


async def cmd_inspect(user_id: str, urls: list[str]) -> int:
    from app.features.google import api, mapping, service
    from app.features.google.properties import url_in_property

    row = await _conn(user_id)
    prop = row.get("selected_property")
    if not prop:
        sys.exit("No property selected. Choose one in the web app first.")
    token = await service.access_token_for(user_id, row)
    gate = service.quota_gate()
    for url in urls:
        if not url_in_property(url, prop):
            print(f"\nSKIPPED {url}: not inside property {prop} (Google would refuse it, and we never try)")
            continue
        before = await gate.usage(prop)
        res = await gate.reserve(prop, manual=True)
        if not res.ok:
            print(f"\nSTOPPED: quota gate says {res.reason} until {res.retry_at}")
            return 2
        raw = await api.inspect_url(token, url, prop)
        after = await gate.usage(prop)
        show(f"RAW Google response: urlInspection/index:inspect for {url}", raw)
        insp = mapping.map_inspection(raw)
        idx = (raw.get("inspectionResult") or {}).get("indexStatusResult") or {}
        show("QuickIndex interpretation", {"status": insp.status, "label": mapping.LABELS[insp.status], **insp.to_dict()})
        print(f"\nkey facts  verdict={idx.get('verdict')}  coverageState={idx.get('coverageState')!r}  lastCrawlTime={idx.get('lastCrawlTime')}"
              f"  googleCanonical={idx.get('googleCanonical')}  userCanonical={idx.get('userCanonical')}")
        print(f"quota accounting: today's counter {before} -> {after} (expected +1)")
    return 0


async def cmd_sitemaps(user_id: str) -> int:
    from app.features.google import api, oauth, service

    row = await _conn(user_id)
    prop = row.get("selected_property") or sys.exit("No property selected.")
    token = await service.access_token_for(user_id, row)
    print("granted scopes include write:", oauth.has_write(row.get("scopes") or ""))
    show("RAW Google response: GET sitemaps", {"sitemap": await api.list_sitemaps(token, prop)})
    return 0


async def cmd_refresh(user_id: str) -> int:
    from app.features.google import crypto, oauth, service

    row = await _conn(user_id)
    refresh = crypto.decrypt_token(user_id, row["refresh_token_enc"])
    oauth.forget_access_token(user_id)  # drop any cached access token so Google must be asked for a new one
    token = await oauth.access_token(user_id, refresh)
    again = await oauth.access_token(user_id, refresh)
    after = await _conn(user_id)
    print("new access token obtained from Google:", bool(token), "| length", len(token), "(value never printed)")
    print("second call served from memory cache (no extra Google call):", token == again)
    print("stored refresh token unchanged in Appwrite:", after["refresh_token_enc"] == row["refresh_token_enc"])
    print("connection status:", after.get("status"))
    return 0


async def cmd_schedule(user_id: str, url: str) -> int:
    from app.features.google import repository as repo
    from app.features.google import service, worker

    res = await service.add_targets(user_id, [url])
    show("add_targets result", res)
    for t in await service.list_targets(user_id):
        if t["url"] == url:
            tid = t["id"]
            break
    else:
        sys.exit("URL was not tracked (see skipped reasons above).")
    due = await repo.list_due("9999", 50)
    mine = next((r for r in due if r["id"] == tid), None)
    if mine and (claimed := await worker._claim(mine, "live-check")):
        await worker.process(claimed)  # the real worker code path, against real Google
    after = await repo.get_target(tid)
    show("target row persisted in Appwrite after the first inspection", {k: after.get(k) for k in
         ("status", "step", "started_at", "next_check_at", "latest_status", "latest_outcome", "latest_at", "last_error", "attempts")})
    show("history rows persisted in Appwrite", [{k: h.get(k) for k in ("inspected_at", "outcome", "status", "trigger", "error_code")}
                                                  for h in await repo.list_history(user_id, tid)])
    print("\nexpected: next_check_at = started_at + 1 day (then +3, +7, +14 days), unless Google reported the page indexed (then no further checks)")
    return 0


async def cmd_disconnect(user_id: str) -> int:
    from app.features.google import api, crypto, oauth, service

    row = await _conn(user_id)
    refresh = crypto.decrypt_token(user_id, row["refresh_token_enc"])
    await service.disconnect(user_id)
    from app.features.google import repository as repo

    print("connection row deleted from Appwrite:", await repo.get_connection(user_id) is None)
    try:
        await api.call("POST", api.TOKEN_URL, data={"client_id": get_settings().GOOGLE_CLIENT_ID, "client_secret": get_settings().GOOGLE_CLIENT_SECRET,
                                                    "refresh_token": refresh, "grant_type": "refresh_token"})
        print("RESULT: the old refresh token STILL WORKS at Google (revocation did not take effect)")
        return 1
    except api.GoogleApiError as e:
        print(f"old refresh token now rejected by Google: {e.code or e.kind} (revocation confirmed)" if e.code == "invalid_grant" else f"unexpected: {e.kind} {e.code}")
    return 0


async def cmd_delete_data(user_id: str) -> int:
    from app.features.google import repository as repo
    from app.features.google import service

    await service.delete_all_data(user_id)
    left = {"connection": await repo.get_connection(user_id) is not None, "targets": len(await repo.list_targets(user_id))}
    print("remaining after delete:", left)
    return 0 if not left["connection"] and left["targets"] == 0 else 1


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user-id", help="QuickIndex (Appwrite) user id whose Google connection to use")
    ap.add_argument("command", choices=["preflight", "status", "properties", "inspect", "sitemaps", "refresh", "schedule", "disconnect", "delete-data"])
    ap.add_argument("urls", nargs="*")
    a = ap.parse_args(argv)
    if a.command == "preflight":
        return await preflight()
    if not get_settings().google_configured:
        sys.exit("Google is not configured. Run `preflight` and follow GOOGLE_SETUP.md.")
    if not a.user_id:
        sys.exit("--user-id is required for this command")
    uid = a.user_id
    if a.command == "inspect":
        return await cmd_inspect(uid, a.urls or sys.exit("give at least one URL"))
    if a.command == "schedule":
        return await cmd_schedule(uid, (a.urls or sys.exit("give a URL"))[0])
    return await {"status": cmd_status, "properties": cmd_properties, "sitemaps": cmd_sitemaps, "refresh": cmd_refresh,
                  "disconnect": cmd_disconnect, "delete-data": cmd_delete_data}[a.command](uid)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
