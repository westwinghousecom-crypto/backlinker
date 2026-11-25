"""Google Search Console orchestration. Every function takes the verified customer id and touches only that
customer's rows."""
import hmac
import json
import logging
from typing import Any
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.core.wakeup import wakeups
from app.features.google import api, crypto, mapping, oauth, repository as repo
from app.features.google.properties import Property, parse_property, url_in_property
from app.features.google.quota import QuotaGate
from app.features.google.schedule import iso, parse, utcnow

log = logging.getLogger(__name__)
EVIDENCE_SOURCE = "Google URL Inspection API"
MAX_URL_LENGTH = 2048


class GoogleError(Exception):
    """A problem the customer can understand and act on. `code` is machine-readable for the UI."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


REAUTH = ("google_reauth_required", "Google access was revoked or expired. Please reconnect Google Search Console.", 409)

_gate: QuotaGate | None = None


def quota_gate() -> QuotaGate:
    global _gate
    if _gate is None:
        s = get_settings()
        _gate = QuotaGate(s.GSC_INSPECT_PER_MINUTE, s.GSC_INSPECT_PER_DAY, repo.AppwriteCounterStore(),
                          manual_reserve=s.GSC_MANUAL_RESERVE)
    return _gate


def reset_gate(gate: QuotaGate | None = None) -> None:
    global _gate
    _gate = gate


def _require_configured() -> None:
    if not get_settings().google_configured:
        raise GoogleError("google_not_configured", "Google integration is not set up on this server yet.", 503)


def map_api_error(e: api.GoogleApiError) -> GoogleError:
    if e.kind == "auth":
        return GoogleError(*REAUTH)
    if e.kind == "permission":
        return GoogleError("google_permission_denied", "Google says this account does not have permission for that property.", 403)
    if e.kind == "quota":
        return GoogleError("quota_exhausted", "Google's inspection limit for this property was reached. Checks resume automatically.", 429)
    if e.kind == "not_found":
        return GoogleError("google_not_found", "Google could not find that property or item.", 404)
    if e.kind == "bad_request":
        return GoogleError("google_bad_request", "Google rejected the request.", 400)
    return GoogleError("google_unavailable", "Google is temporarily unavailable. Please try again.", 503)


# ---------------------------------------------------------------------------- connection

async def _active_connection(user_id: str) -> dict[str, Any]:
    _require_configured()
    row = await repo.get_connection(user_id)
    if row is None:
        raise GoogleError("google_not_connected", "Connect Google Search Console first.", 409)
    if row.get("status") != "active":
        raise GoogleError(*REAUTH)
    return row


async def access_token_for(user_id: str, row: dict[str, Any]) -> str:
    """A working access token for this customer, or GoogleError(reauth) after marking the connection revoked."""
    try:
        refresh = crypto.decrypt_token(user_id, row["refresh_token_enc"])
        return await oauth.access_token(user_id, refresh)
    except (crypto.CryptoError, oauth.ReauthRequired):
        await repo.upsert_connection(user_id, {"status": "revoked", "error_code": "invalid_grant"})
        raise GoogleError(*REAUTH)
    except api.GoogleApiError as e:
        raise map_api_error(e)


async def get_status(user_id: str) -> dict[str, Any]:
    s = get_settings()
    base: dict[str, Any] = {
        "configured": s.google_configured, "connected": False, "state": None, "email": None,
        "can_write": False, "reauth_required": False, "selected_property": None, "quota": None,
    }
    if not s.google_configured:
        return base
    row = await repo.get_connection(user_id)
    if row is None:
        return base
    scopes = row.get("scopes") or ""
    prop = row.get("selected_property")
    quota = None
    if prop:
        try:
            quota = {
                "property": prop, "per_day_limit": s.GSC_INSPECT_PER_DAY,
                "used_today": await quota_gate().usage(prop), "per_minute_limit": s.GSC_INSPECT_PER_MINUTE,
            }
        except Exception:
            log.warning("quota usage unavailable")
    return {
        **base, "connected": True, "state": row.get("status"), "email": row.get("google_email"),
        "can_write": oauth.has_write(scopes), "reauth_required": row.get("status") != "active",
        "selected_property": prop, "quota": quota,
    }


def begin_connect(user_id: str, write: bool) -> tuple[str, str]:
    """Returns (consent URL, browser binding secret). The secret goes into an HttpOnly cookie, never into the URL."""
    _require_configured()
    binding = oauth.new_binding()
    return oauth.authorization_url(user_id, write, binding), binding


async def complete_callback(code: str | None, state: str | None, error: str | None, binding: str | None = None) -> str:
    """Finish the OAuth flow. Returns a short result code that is safe to put in a redirect URL.

    The state must be (1) sealed by us and fresh, (2) presented by the SAME browser that started the flow (its cookie
    matches the binding inside the state), and (3) used only once. Only then is anything exchanged with Google."""
    if not get_settings().google_configured:
        return "not_configured"
    try:
        sealed = crypto.open_state(state or "")
        user_id, verifier, nonce, bound = str(sealed["u"]), str(sealed["v"]), str(sealed["n"]), str(sealed["b"])
    except (crypto.CryptoError, KeyError):
        return "invalid_state"
    if not binding or not hmac.compare_digest(oauth.binding_hash(binding), bound):
        return "invalid_state"  # a different browser (or none) is presenting this state
    try:
        first_use = await repo.claim_oauth_state(nonce, user_id)
    except Exception:
        return "exchange_failed"
    if not first_use:
        return "invalid_state"  # replay
    if error or not code:
        return "access_denied"
    try:
        tokens = await oauth.exchange_code(code, verifier)
    except api.GoogleApiError:
        return "exchange_failed"
    if not oauth.has_read(tokens.scope):
        return "scope_missing"  # the customer unticked the Search Console permission on the consent screen
    existing = await repo.get_connection(user_id)
    if tokens.refresh_token:
        encrypted = crypto.encrypt_token(user_id, tokens.refresh_token)
    elif existing and existing.get("refresh_token_enc"):
        encrypted = existing["refresh_token_enc"]  # Google did not issue a new one: keep the one we have
    else:
        return "exchange_failed"
    await repo.upsert_connection(user_id, {
        "refresh_token_enc": encrypted,
        "google_email": tokens.email, "scopes": tokens.scope[:512], "status": "active", "error_code": None,
        "selected_property": (existing or {}).get("selected_property"),
    })
    oauth.forget_access_token(user_id)
    await _resume_paused(user_id)
    return "connected"


async def _resume_paused(user_id: str) -> None:
    now = iso(utcnow())
    paused = await repo.list_paused(user_id)
    for t in paused:
        await repo.update_target(t["id"], {"status": "pending", "next_check_at": now, "locked_by": None})
    if paused:
        wakeups.notify("gsc")


async def disconnect(user_id: str) -> None:
    row = await repo.get_connection(user_id)
    if row is None:
        return
    try:
        await oauth.revoke(crypto.decrypt_token(user_id, row["refresh_token_enc"]))
    except (crypto.CryptoError, crypto.NotConfigured):
        pass
    await repo.delete_connection(user_id)
    oauth.forget_access_token(user_id)


async def delete_all_data(user_id: str) -> None:
    """Disconnect AND delete every tracked URL and inspection record for this customer."""
    await disconnect(user_id)
    await repo.delete_user_data(user_id)


# ---------------------------------------------------------------------------- properties

async def list_properties(user_id: str) -> list[Property]:
    row = await _active_connection(user_id)
    token = await access_token_for(user_id, row)
    try:
        entries = await api.list_sites(token)
    except api.GoogleApiError as e:
        raise map_api_error(e)
    props = [parse_property(e) for e in entries if e.get("siteUrl")]
    return sorted(props, key=lambda p: (p.type != "domain", p.site_url))


async def select_property(user_id: str, site_url: str) -> str:
    match = next((p for p in await list_properties(user_id) if p.site_url == site_url), None)
    if match is None:
        raise GoogleError("property_not_usable", "That property is not available to your Google account.", 400)
    if not match.verified:
        raise GoogleError("property_not_usable", "That property is not verified in Search Console, so Google will not inspect it.", 400)
    await repo.upsert_connection(user_id, {"selected_property": match.site_url})
    return match.site_url


async def _selected_property(user_id: str) -> tuple[dict[str, Any], str]:
    row = await _active_connection(user_id)
    prop = row.get("selected_property")
    if not prop:
        raise GoogleError("property_not_selected", "Choose a Search Console property first.", 409)
    return row, prop


# ---------------------------------------------------------------------------- tracked URLs

def _valid_http_url(url: str) -> bool:
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.hostname) and len(url) <= MAX_URL_LENGTH


async def add_targets(user_id: str, urls: list[str]) -> dict[str, Any]:
    _row, prop = await _selected_property(user_id)
    limit = get_settings().GSC_MAX_TARGETS_PER_USER
    if await repo.count_targets(user_id) + len(urls) > limit:
        raise GoogleError("too_many_urls", f"You can track at most {limit:,} URLs.", 429)

    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    candidates: list[str] = []
    for raw in urls:
        url = raw.strip()
        if not url:
            continue
        if url in seen:
            skipped.append({"url": url[:200], "reason": "duplicate"})
        elif not _valid_http_url(url):
            skipped.append({"url": url[:200], "reason": "invalid_url"})
        elif not url_in_property(url, prop):  # a customer can only ever inspect URLs inside their own property
            skipped.append({"url": url[:200], "reason": "outside_property"})
        else:
            candidates.append(url)
        seen.add(url)

    ids = {u: repo.target_id(user_id, prop, u) for u in candidates}
    already = await repo.existing_target_ids(list(ids.values())) if ids else set()
    now = iso(utcnow())
    rows = []
    for u, tid in ids.items():
        if tid in already:
            skipped.append({"url": u[:200], "reason": "duplicate"})
            continue
        rows.append({
            "$id": tid, "user_id": user_id, "property": prop, "url": u, "started_at": now, "next_check_at": now,
            "step": 0, "status": "pending", "attempts": 0, "manual": False, "latest_status": mapping.UNKNOWN,
        })
    created, errors = await repo.create_targets(user_id, rows) if rows else (0, [])
    if errors:
        log.error("%d tracked URLs could not be stored", len(errors))
    if created:
        wakeups.notify("gsc")
    return {"added": created, "skipped": skipped}


def _inspection_dict(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def target_view(row: dict[str, Any]) -> dict[str, Any]:
    status = mapping.display_status(row.get("latest_status"), row.get("latest_outcome"))
    last_known = row.get("latest_status") if status == "failed" else None
    return {
        "id": row["id"], "url": row["url"], "property": row["property"], "display_status": status,
        "label": mapping.LABELS[status], "evidence_source": EVIDENCE_SOURCE,
        "last_inspected_at": row.get("latest_at"), "next_check_at": row.get("next_check_at"),
        "state": row.get("status") or "pending", "last_known_status": last_known,
        "error_code": row.get("last_error") if status == "failed" else None,
        "error_message": ERROR_TEXT.get(row.get("last_error") or "") if status == "failed" else None,
        "started_at": row.get("started_at"), "inspection": _inspection_dict(row.get("latest_result")),
    }


ERROR_TEXT = {
    "permission_denied": "Google says your account cannot inspect this property.",
    "bad_request": "Google could not inspect this URL.",
    "property_not_found": "Google could not find this property.",
    "google_unavailable": "Google was temporarily unavailable after several tries.",
    "google_auth_error": "Google rejected the saved access. Reconnect Google Search Console.",
}


async def list_targets(user_id: str) -> list[dict[str, Any]]:
    rows = await repo.list_targets(user_id)
    rows.sort(key=lambda r: (r.get("started_at") or "", r["url"]))
    return [target_view(r) for r in rows if r.get("user_id") == user_id]  # belt and braces


async def _owned_target(user_id: str, tid: str) -> dict[str, Any]:
    row = await repo.get_target(tid)
    if row is None or row.get("user_id") != user_id:
        raise GoogleError("not_found", "URL not found.", 404)  # a stranger's id looks the same as a missing one
    return row


async def history(user_id: str, tid: str) -> list[dict[str, Any]]:
    await _owned_target(user_id, tid)
    out = []
    for h in await repo.list_history(user_id, tid):
        if h.get("user_id") != user_id:
            continue
        status = h.get("status") or mapping.UNKNOWN
        out.append({
            "id": h["id"], "inspected_at": h.get("inspected_at"), "outcome": h.get("outcome"),
            "status": status, "label": mapping.LABELS.get(status, "Unknown"), "error_code": h.get("error_code"),
            "trigger": h.get("trigger"), "inspection": _inspection_dict(h.get("result")),
        })
    return out


async def recheck(user_id: str, tid: str) -> None:
    row = await _owned_target(user_id, tid)
    if row.get("status") == "processing":
        return
    await repo.update_target(tid, {"status": "pending", "next_check_at": iso(utcnow()), "manual": True, "attempts": 0, "locked_by": None})
    wakeups.notify("gsc")


async def remove_target(user_id: str, tid: str) -> None:
    await _owned_target(user_id, tid)
    await repo.delete_history(tid)
    await repo.delete_target(tid)


# ---------------------------------------------------------------------------- sitemaps

def _sitemap_view(s: dict) -> dict:
    return {
        "path": s.get("path"), "last_submitted": s.get("lastSubmitted"), "last_downloaded": s.get("lastDownloaded"),
        "is_pending": bool(s.get("isPending")), "is_sitemaps_index": bool(s.get("isSitemapsIndex")), "type": s.get("type"),
        "warnings": int(s.get("warnings") or 0), "errors": int(s.get("errors") or 0),
    }


async def list_sitemaps(user_id: str) -> dict[str, Any]:
    row, prop = await _selected_property(user_id)
    token = await access_token_for(user_id, row)
    try:
        items = await api.list_sitemaps(token, prop)
    except api.GoogleApiError as e:
        raise map_api_error(e)
    return {"sitemaps": [_sitemap_view(s) for s in items], "can_write": oauth.has_write(row.get("scopes") or "")}


async def submit_sitemap(user_id: str, url: str) -> None:
    row, prop = await _selected_property(user_id)
    if not oauth.has_write(row.get("scopes") or ""):
        raise GoogleError("write_permission_required", "Submitting a sitemap needs extra permission. Grant write access first.", 403)
    url = url.strip()
    if not _valid_http_url(url) or not url_in_property(url, prop):
        raise GoogleError("url_outside_property", "The sitemap URL must be inside your selected property.", 400)
    token = await access_token_for(user_id, row)
    try:
        await api.submit_sitemap(token, prop, url)
    except api.GoogleApiError as e:
        raise map_api_error(e)
