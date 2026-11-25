"""Password recovery and email verification, on top of Appwrite's official APIs.

Why these go through the API instead of straight from the browser:
  * Account enumeration: recovery ALWAYS answers the same way (HTTP 202, same text, similar timing) whether or not
    the address has an account. Appwrite's own error for an unknown address is swallowed here.
  * Abuse: requests are limited per IP and per address (hashed, never stored), so the endpoint cannot be used to
    mail-bomb someone or to probe addresses at speed.
  * The link in the email points at FRONTEND_URL from server configuration, never at a host taken from the request.
Completing a reset or a verification (the customer clicking the emailed link) is done with Appwrite's own API from the
browser; those links carry a one-time secret that only Appwrite can validate.
"""
import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timezone

from appwrite.client import Client
from appwrite.services.account import Account
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.core.security import check_rate_limit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/account", tags=["account"])

NEUTRAL = {"message": "If an account exists for that address, we have sent instructions to it."}
MIN_RESPONSE_SECONDS = 0.7  # evens out timing between "sent" and "no such account"
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,63}$")


class RecoveryRequest(BaseModel):
    email: str


def _client() -> Client:
    s = get_settings()
    c = Client()
    c.set_endpoint(s.APPWRITE_ENDPOINT)
    c.set_project(s.APPWRITE_PROJECT_ID)
    return c


def _frontend(path: str) -> str:
    return f"{get_settings().FRONTEND_URL.rstrip('/')}{path}"


def _client_ip(request: Request) -> str:
    # Behind a reverse proxy, configure the proxy / uvicorn --proxy-headers so this is the real client address.
    return request.client.host if request.client else "unknown"


def _send_recovery(email: str) -> None:
    Account(_client()).create_recovery(email=email, url=_frontend("/reset-password"))


@router.post("/recovery", status_code=202)
async def request_recovery(body: RecoveryRequest, request: Request) -> dict[str, str]:
    s = get_settings()
    started = time.monotonic()
    email = body.email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")

    ip_ok = check_rate_limit(f"recovery-ip:{_client_ip(request)}", s.RECOVERY_PER_IP, window=900)
    digest = hashlib.sha256(email.encode()).hexdigest()  # the address itself is never stored or logged
    email_ok = check_rate_limit(f"recovery-email:{digest}", s.RECOVERY_PER_EMAIL, window=3600)
    if not (ip_ok and email_ok):
        # Same answer for every address, so this reveals nothing about which ones have accounts.
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    try:
        await asyncio.to_thread(_send_recovery, email)
    except Exception as e:  # unknown address, Appwrite down, mail failure: the caller must not be able to tell
        log.info("recovery request not sent (%s)", type(e).__name__)
    await asyncio.sleep(max(0.0, MIN_RESPONSE_SECONDS - (time.monotonic() - started)))
    return NEUTRAL


def _send_verification(token: str) -> None:
    s = get_settings()
    c = Client()
    c.set_endpoint(s.APPWRITE_ENDPOINT)
    c.set_project(s.APPWRITE_PROJECT_ID)
    c.set_jwt(token)
    Account(c).create_email_verification(url=_frontend("/verify-email"))  # create_verification is deprecated


@router.post("/verification", status_code=202)
async def resend_verification(user: AuthUser = Depends(current_user)) -> dict[str, object]:
    """Send (or resend) the verification email to the signed-in customer's own address."""
    s = get_settings()
    if user.email_verified:
        return {"message": "Your email address is already verified.", "already_verified": True}
    if not check_rate_limit(f"verify-cooldown:{user.id}", 1, window=s.VERIFICATION_RESEND_COOLDOWN):
        raise HTTPException(status_code=429, detail=f"Please wait {s.VERIFICATION_RESEND_COOLDOWN} seconds before asking again.")
    if not check_rate_limit(f"verify-hour:{user.id}", s.VERIFICATION_PER_HOUR, window=3600):
        raise HTTPException(status_code=429, detail="Too many verification emails. Please try again later.")
    try:
        await asyncio.to_thread(_send_verification, user.token)
    except Exception as e:
        log.warning("verification email failed (%s)", type(e).__name__)
        raise HTTPException(status_code=502, detail="Could not send the verification email. Please try again.")
    return {"message": "Verification email sent. Check your inbox.", "already_verified": False}


# ---------------------------------------------------------------------------- data export and account deletion

from fastapi import Response  # noqa: E402
from pydantic import BaseModel as _BaseModel  # noqa: E402

from app.core.auth import AuthUser as _AuthUser, current_user as _current_user, rate_limited_user as _rate_limited_user  # noqa: E402
from app.core import auth as _auth  # noqa: E402
from app.features.account import data as account_data  # noqa: E402


class DeleteAccountRequest(_BaseModel):
    confirm: str


@router.get("/export")
async def export_my_data(user: _AuthUser = Depends(_rate_limited_user)) -> Response:
    """Everything QuickIndex stores about the signed-in customer, as a JSON download. 3 per hour."""
    if not check_rate_limit(f"export:{user.id}", 3, window=3600):
        raise HTTPException(status_code=429, detail="You can export your data 3 times per hour. Please try again later.")
    body = await account_data.export_data(user)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(body, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="quickindex-export-{stamp}.json"', "Cache-Control": "no-store"})


@router.delete("", status_code=204)
async def delete_my_account(body: DeleteAccountRequest, user: _AuthUser = Depends(_rate_limited_user)) -> Response:
    """Revoke Google, erase every row the customer owns, then remove the account. Safe to repeat."""
    if body.confirm != "DELETE":
        raise HTTPException(status_code=400, detail='Type DELETE (in capitals) to confirm.')
    if not check_rate_limit(f"delete-account:{user.id}", 5, window=3600):
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
    try:
        result = await account_data.delete_account(user)
    except Exception as e:
        log.exception("account deletion failed part-way (%s); the customer can retry", type(e).__name__)
        raise HTTPException(status_code=502, detail="Deleting your account did not finish. Please try again.")
    log.info("account %s deleted: %s", user.id, {"user": result["user"], "rows": sum(result["rows"].values())})
    _auth._cache.pop(hashlib.sha256(user.token.encode()).hexdigest(), None)  # stop honouring this session straight away
    return Response(status_code=204)
