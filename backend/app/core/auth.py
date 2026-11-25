"""Customer authentication for the API.

The browser signs in with Appwrite Auth and sends a short-lived Appwrite JWT as ``Authorization: Bearer``.
Here the token is verified by asking Appwrite who it belongs to (``GET /account`` with that JWT). The
user id used everywhere else comes ONLY from this verified answer, never from a request body, query
string or header the browser controls.

The server's admin API key is not used for verification, so it needs no user-management scopes.
"""
import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field

from appwrite.client import Client
from appwrite.exception import AppwriteException
from appwrite.services.account import Account
from fastapi import Depends, HTTPException, Request

from app.core.config import get_settings
from app.core.security import check_rate_limit

log = logging.getLogger(__name__)

CACHE_TTL = 30.0  # seconds; keeps 2.5 s status polling from calling Appwrite on every request
CACHE_MAX = 2000
MAX_TOKEN_LENGTH = 4096


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None = None
    email_verified: bool = False
    token: str = field(default="", repr=False, compare=False)  # the caller's own JWT; never logged


class UpstreamError(Exception):
    """Appwrite could not be reached or failed: not the caller's fault, so not a 401."""


_cache: dict[str, tuple[float, AuthUser]] = {}


def _verify_sync(token: str) -> AuthUser | None:
    """Ask Appwrite who owns this JWT. Returns None if the token is invalid or the account is disabled."""
    s = get_settings()
    client = Client()
    client.set_endpoint(s.APPWRITE_ENDPOINT)
    client.set_project(s.APPWRITE_PROJECT_ID)
    client.set_jwt(token)
    try:
        user = Account(client).get()
    except AppwriteException as e:
        if e.code in (401, 403):
            return None
        raise UpstreamError(str(e))
    except Exception as e:
        raise UpstreamError(str(e))
    if getattr(user, "status", True) is False:
        return None
    return AuthUser(
        id=user.id,
        email=getattr(user, "email", None),
        email_verified=bool(getattr(user, "emailverification", False)),
        token=token,
    )


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


async def current_user(request: Request) -> AuthUser:
    """FastAPI dependency: the signed-in customer, or 401."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or len(token) > MAX_TOKEN_LENGTH:
        raise _unauthorized()

    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]

    try:
        user = await asyncio.to_thread(_verify_sync, token)
    except UpstreamError:
        log.exception("Appwrite token verification failed")
        raise HTTPException(status_code=503, detail="Sign-in service unavailable. Please try again.")
    if user is None:
        _cache.pop(key, None)
        raise _unauthorized("Invalid or expired session")

    if len(_cache) >= CACHE_MAX:
        for k in [k for k, (exp, _) in _cache.items() if exp <= now] or list(_cache)[: CACHE_MAX // 2]:
            _cache.pop(k, None)
    _cache[key] = (now + CACHE_TTL, user)
    return user


async def rate_limited_user(user: AuthUser = Depends(current_user)) -> AuthUser:
    """Signed-in customer who is also within the per-customer request rate limit (for write endpoints)."""
    limit = get_settings().RATE_LIMIT_PER_MINUTE
    if limit > 0 and not check_rate_limit(f"user:{user.id}", limit):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")
    return user
