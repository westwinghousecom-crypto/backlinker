"""Encrypted export and restore of QuickIndex's Appwrite tables.

A backup is ONE file: every row of the QuickIndex tables as JSON, encrypted with Fernet (AES + HMAC, so tampering or the
wrong key is detected), plus a small plain manifest (row counts per table and a SHA-256 of the unencrypted content).

Keys: BACKUP_ENCRYPTION_KEY encrypts the file. The Google refresh tokens INSIDE `google_connections` are separately
encrypted with TOKEN_ENCRYPTION_KEY and stay that way, so a full restore needs BOTH keys. Skipped on purpose:
`google_quota` and `google_oauth_states` (short-lived counters and nonces that are safe to lose).
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from appwrite.exception import AppwriteException
from appwrite.query import Query
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.bulk import owner_permissions

FORMAT = 1
PAGE = 100
# export name -> the Settings attribute holding the Appwrite table id
BACKUP_TABLES = {
    "urls": "APPWRITE_URLS_TABLE_ID",
    "check_batches": "APPWRITE_CHECK_BATCHES_TABLE_ID",
    "checks": "APPWRITE_CHECKS_TABLE_ID",
    "batch_sharing": "APPWRITE_BATCH_SHARING_TABLE_ID",
    "google_connections": "APPWRITE_GOOGLE_CONNECTIONS_TABLE_ID",
    "gsc_targets": "APPWRITE_GSC_TARGETS_TABLE_ID",
    "gsc_history": "APPWRITE_GSC_HISTORY_TABLE_ID",
}


class BackupError(Exception):
    pass


def _fernet(key: str) -> MultiFernet:
    keys = [k.strip() for k in (key or "").split(",") if k.strip()]
    if not keys:
        raise BackupError("BACKUP_ENCRYPTION_KEY is not set. Generate one with: "
                          "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except (ValueError, TypeError):
        raise BackupError("BACKUP_ENCRYPTION_KEY is not a valid Fernet key")


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def export_tables(db, database_id: str, table_ids: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Read every row of every backed-up table (paginated). `table_ids` maps export name -> Appwrite table id."""
    out: dict[str, list[dict[str, Any]]] = {}
    for name, table in table_ids.items():
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            res = db.list_rows(database_id=database_id, table_id=table, queries=[Query.limit(PAGE), Query.offset(offset)])
            rows.extend({"id": r.id, "created_at": r.createdat, "updated_at": r.updatedat, "data": dict(r.data)} for r in res.rows)
            if len(res.rows) < PAGE:
                break
            offset += PAGE
        out[name] = rows
    return out


def make_backup(tables: dict[str, list[dict[str, Any]]], key: str, now: datetime | None = None) -> tuple[bytes, dict[str, Any]]:
    """Returns (encrypted bytes, manifest). The manifest holds no row data."""
    fernet = _fernet(key)
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    plain = _canonical({"format": FORMAT, "created_at": stamp, "tables": tables})
    manifest = {
        "format": FORMAT, "created_at": stamp, "sha256": hashlib.sha256(plain).hexdigest(),
        "tables": {name: len(rows) for name, rows in tables.items()}, "total_rows": sum(len(r) for r in tables.values()),
    }
    return fernet.encrypt(plain), manifest


def open_backup(blob: bytes, key: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decrypt and (if a manifest is given) verify the hash and per-table counts. Raises BackupError on any problem."""
    fernet = _fernet(key)
    try:
        plain = fernet.decrypt(blob)
    except InvalidToken:
        raise BackupError("cannot decrypt: wrong BACKUP_ENCRYPTION_KEY, or the file was modified or is corrupt")
    try:
        payload = json.loads(plain)
    except ValueError:
        raise BackupError("decrypted content is not valid JSON")
    if payload.get("format") != FORMAT:
        raise BackupError(f"unsupported backup format {payload.get('format')!r}")
    if manifest is not None:
        if hashlib.sha256(plain).hexdigest() != manifest.get("sha256"):
            raise BackupError("SHA-256 does not match the manifest")
        counts = {name: len(rows) for name, rows in payload["tables"].items()}
        if counts != manifest.get("tables"):
            raise BackupError(f"row counts differ from the manifest: {counts} vs {manifest.get('tables')}")
    return payload


def _newer(a: str | None, b: str | None) -> bool:
    """True if timestamp a is strictly later than timestamp b."""
    if not a or not b:
        return False
    return datetime.fromisoformat(a.replace("Z", "+00:00")) > datetime.fromisoformat(b.replace("Z", "+00:00"))


def restore(db, database_id: str, table_ids: dict[str, str], payload: dict[str, Any], force: bool = False,
            dry_run: bool = False) -> dict[str, dict[str, int]]:
    """Put rows back by id. Missing rows are created (owner-only read permission for rows with a user_id); existing rows
    are updated, except that a row CHANGED AFTER the backup is kept unless `force`. With dry_run nothing is written."""
    report: dict[str, dict[str, int]] = {}
    for name, rows in payload["tables"].items():
        table = table_ids[name]
        counts = {"created": 0, "updated": 0, "unchanged": 0, "kept_newer": 0}
        for row in rows:
            try:
                existing = db.get_row(database_id=database_id, table_id=table, row_id=row["id"])
            except AppwriteException as e:
                if e.code != 404:
                    raise
                existing = None
            if existing is None:
                if not dry_run:
                    uid = row["data"].get("user_id")
                    db.create_row(database_id=database_id, table_id=table, row_id=row["id"], data=row["data"],
                                  permissions=owner_permissions(uid) if uid else None)
                counts["created"] += 1
            elif dict(existing.data) == row["data"]:
                counts["unchanged"] += 1
            elif _newer(existing.updatedat, row["updated_at"]) and not force:
                counts["kept_newer"] += 1
            else:
                if not dry_run:
                    db.update_row(database_id=database_id, table_id=table, row_id=row["id"], data=row["data"])
                counts["updated"] += 1
        report[name] = counts
    return report
