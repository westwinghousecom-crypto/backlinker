"""Google OAuth 2.0 (authorization-code flow with PKCE) for Search Console.

Security properties:
  * ``state`` is sealed (encrypted + authenticated + 10 min expiry) and carries the QuickIndex user id and the PKCE
    verifier. The callback links Google ONLY to the user named in the sealed state, so a forged or replayed state
    cannot attach someone else's Google account to a victim, and nothing about the verifier is visible in the URL.
  * PKCE (S256) on top of the client secret.
  * Minimum scopes: ``webmasters.readonly`` by default. The write scope ``webmasters`` is requested only when the
    customer explicitly asks to submit sitemaps. ``openid email`` only identify which Google account was connected.
  * The refresh token is encrypted before it touches the database. Access tokens live in memory only.
  * Nothing here logs a code, token or secret.
"""
import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

from app.core.config import get_settings
from app.features.google import api, crypto

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPE_READ = "https://www.googleapis.com/auth/webmasters.readonly"
SCOPE_WRITE = "https://www.googleapis.com/auth/webmasters"
IDENTITY_SCOPES = ("openid", "email")
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
EXPIRY_MARGIN = 120  # refresh access tokens two minutes early


class ReauthRequired(Exception):
    """The stored refresh token no longer works (revoked, expired, or the app was removed from the account)."""


@dataclass
class TokenSet:
    refresh_token: str | None
    access_token: str
    expires_in: int
    scope: str
    email: str | None


def has_read(scope_string: str) -> bool:
    scopes = scope_string.split()
    return SCOPE_READ in scopes or SCOPE_WRITE in scopes  # the write scope includes read access


def has_write(scope_string: str) -> bool:
    return SCOPE_WRITE in scope_string.split()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def binding_hash(binding: str) -> str:
    return hashlib.sha256(binding.encode()).hexdigest()[:32]


def new_binding() -> str:
    """A random secret kept in an HttpOnly cookie in the browser that starts the flow (never in the URL)."""
    return secrets.token_urlsafe(32)


def authorization_url(user_id: str, write: bool, binding: str) -> str:
    s = get_settings()
    verifier = secrets.token_urlsafe(64)
    state = crypto.seal_state({"u": user_id, "v": verifier, "w": bool(write), "n": secrets.token_urlsafe(16), "b": binding_hash(binding)})
    params = {
        "client_id": s.GOOGLE_CLIENT_ID,
        "redirect_uri": s.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join([*IDENTITY_SCOPES, SCOPE_WRITE if write else SCOPE_READ]),
        "state": state,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
        "access_type": "offline",  # we need a refresh token for scheduled rechecks
        "prompt": "consent",  # make Google return that refresh token every time
        "include_granted_scopes": "true",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _email_from_id_token(id_token: str | None, client_id: str) -> str | None:
    """Read the email claim. The token arrived straight from Google's token endpoint over TLS, so its payload is
    trusted for display; the audience and issuer are still checked."""
    if not id_token:
        return None
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return None
    if claims.get("aud") != client_id or claims.get("iss") not in GOOGLE_ISSUERS:
        return None
    email = claims.get("email")
    return str(email)[:320] if email else None


async def exchange_code(code: str, verifier: str) -> TokenSet:
    s = get_settings()
    body = await api.call(
        "POST", api.TOKEN_URL,
        data={
            "client_id": s.GOOGLE_CLIENT_ID,
            "client_secret": s.GOOGLE_CLIENT_SECRET,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": s.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
    )
    return TokenSet(
        refresh_token=body.get("refresh_token"),
        access_token=str(body.get("access_token", "")),
        expires_in=int(body.get("expires_in", 3600)),
        scope=str(body.get("scope", "")),
        email=_email_from_id_token(body.get("id_token"), s.GOOGLE_CLIENT_ID),
    )


_access: dict[str, tuple[float, str]] = {}  # user_id -> (monotonic expiry, access token); memory only


def forget_access_token(user_id: str) -> None:
    _access.pop(user_id, None)


async def access_token(user_id: str, refresh_token: str) -> str:
    """A valid access token for this customer, refreshing when needed. Raises ReauthRequired if Google refuses."""
    hit = _access.get(user_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    s = get_settings()
    try:
        body = await api.call(
            "POST", api.TOKEN_URL,
            data={
                "client_id": s.GOOGLE_CLIENT_ID,
                "client_secret": s.GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    except api.GoogleApiError as e:
        if e.code == "invalid_grant" or e.kind == "auth":
            forget_access_token(user_id)
            raise ReauthRequired() from e
        raise
    token = str(body.get("access_token", ""))
    if not token:
        raise ReauthRequired()
    _access[user_id] = (time.monotonic() + max(int(body.get("expires_in", 3600)) - EXPIRY_MARGIN, 30), token)
    return token


async def revoke(refresh_token: str) -> None:
    """Tell Google to invalidate the grant (best effort: failure must not block disconnecting)."""
    try:
        await api.call("POST", api.REVOKE_URL, data={"token": refresh_token})
    except api.GoogleApiError:
        pass
