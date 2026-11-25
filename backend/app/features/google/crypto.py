"""Encryption for Google refresh tokens and OAuth state. Keys come from TOKEN_ENCRYPTION_KEY (server env only).

* Refresh tokens are stored encrypted (Fernet: AES-128-CBC + HMAC-SHA256), bound to the owning customer, so a row
  copied to another customer's record cannot be decrypted into a usable token for them.
* OAuth ``state`` is sealed (encrypted and authenticated, with an expiry), so it cannot be forged or read.
* Several comma-separated keys are accepted: the first encrypts, all can decrypt, which allows key rotation.
"""
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


class CryptoError(Exception):
    """Token or state is invalid, tampered with, expired, or belongs to someone else."""


class NotConfigured(Exception):
    pass


def generate_key() -> str:
    return Fernet.generate_key().decode()


def _fernet() -> MultiFernet:
    keys = [k.strip() for k in get_settings().TOKEN_ENCRYPTION_KEY.split(",") if k.strip()]
    if not keys:
        raise NotConfigured("TOKEN_ENCRYPTION_KEY is not set")
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except (ValueError, TypeError) as e:
        raise NotConfigured("TOKEN_ENCRYPTION_KEY is not a valid Fernet key") from e


def encrypt_token(user_id: str, token: str) -> str:
    return _fernet().encrypt(json.dumps({"u": user_id, "t": token}).encode()).decode()


def decrypt_token(user_id: str, blob: str) -> str:
    try:
        data = json.loads(_fernet().decrypt(blob.encode()))
    except (InvalidToken, ValueError):
        raise CryptoError("stored token cannot be decrypted")
    if data.get("u") != user_id:
        raise CryptoError("stored token belongs to a different customer")
    return str(data["t"])


def seal_state(payload: dict) -> str:
    return _fernet().encrypt(json.dumps(payload).encode()).decode()


def open_state(sealed: str, max_age_seconds: int = 600) -> dict:
    try:
        return json.loads(_fernet().decrypt(sealed.encode(), ttl=max_age_seconds))
    except (InvalidToken, ValueError):
        raise CryptoError("state is invalid or expired")
