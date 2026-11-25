"""Verify or restore an encrypted QuickIndex backup.

    .venv\\Scripts\\python scripts\\restore_backup.py FILE.json.enc --verify     decrypt, check SHA-256 and counts; writes nothing
    .venv\\Scripts\\python scripts\\restore_backup.py FILE.json.enc --dry-run    show what a restore WOULD create/update; writes nothing
    .venv\\Scripts\\python scripts\\restore_backup.py FILE.json.enc --restore    put rows back (by id; owner-only read permission re-created)
                                                                              add --force to overwrite rows changed after the backup

The manifest is read from  FILE.manifest.json  next to the backup. Needs BACKUP_ENCRYPTION_KEY in backend/.env.
Google refresh tokens stay encrypted with TOKEN_ENCRYPTION_KEY: keep that key too, or customers must reconnect Google.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import backup  # noqa: E402
from app.core.appwrite_client import get_tables_db  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def load(path: Path):
    s = get_settings()
    manifest_path = path.with_name(path.name.removesuffix(".json.enc") + ".manifest.json")
    if not manifest_path.exists():
        sys.exit(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        return backup.open_backup(path.read_bytes(), s.BACKUP_ENCRYPTION_KEY, manifest), manifest
    except backup.BackupError as e:
        sys.exit(f"VERIFY FAILED: {e}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--restore", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite rows that changed after the backup was taken")
    a = ap.parse_args(argv)

    payload, manifest = load(a.file)
    print(f"OK: decrypted, SHA-256 matches, counts match {manifest['tables']} (taken {manifest['created_at']})")
    if a.verify:
        return 0
    s = get_settings()
    table_ids = {name: getattr(s, attr) for name, attr in backup.BACKUP_TABLES.items()}
    report = backup.restore(get_tables_db(), s.APPWRITE_DATABASE_ID, table_ids, payload, force=a.force, dry_run=a.dry_run)
    print(("DRY RUN, nothing written. " if a.dry_run else "RESTORED. ") + "per table:")
    for name, c in report.items():
        print(f"  {name}: {c}")
    kept = sum(c["kept_newer"] for c in report.values())
    if kept:
        print(f"{kept} row(s) were changed after the backup and were kept; use --force to overwrite them.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
