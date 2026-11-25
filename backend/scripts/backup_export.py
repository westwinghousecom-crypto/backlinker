"""Export every QuickIndex Appwrite table to one encrypted, dated file.

    .venv\\Scripts\\python scripts\\backup_export.py [--out-dir backups]

Writes  backups/quickindex-YYYYMMDD-HHMMSS.json.enc  and  backups/quickindex-YYYYMMDD-HHMMSS.manifest.json
(row counts per table + SHA-256 of the unencrypted content). Refuses to run without BACKUP_ENCRYPTION_KEY (backend/.env).
Keep the key somewhere other than the backups, and test a restore (see restore_backup.py --verify / --dry-run).
Both BACKUP_ENCRYPTION_KEY and TOKEN_ENCRYPTION_KEY are needed to fully restore Google connections.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import backup  # noqa: E402
from app.core.appwrite_client import get_tables_db  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def run(out_dir: str = "backups", now: datetime | None = None) -> tuple[Path, Path, dict]:
    s = get_settings()
    if not s.BACKUP_ENCRYPTION_KEY:
        sys.exit("Refusing to run: BACKUP_ENCRYPTION_KEY is not set in backend/.env (an unencrypted backup would expose customer data).")
    table_ids = {name: getattr(s, attr) for name, attr in backup.BACKUP_TABLES.items()}
    tables = backup.export_tables(get_tables_db(), s.APPWRITE_DATABASE_ID, table_ids)
    now = now or datetime.now(timezone.utc)
    blob, manifest = backup.make_backup(tables, s.BACKUP_ENCRYPTION_KEY, now)
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"quickindex-{now.strftime('%Y%m%d-%H%M%S')}"
    data_path, manifest_path = folder / f"{stem}.json.enc", folder / f"{stem}.manifest.json"
    data_path.write_bytes(blob)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return data_path, manifest_path, manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default="backups")
    args = ap.parse_args()
    data_path, manifest_path, manifest = run(args.out_dir)
    print(f"wrote {data_path} ({data_path.stat().st_size:,} bytes, encrypted) and {manifest_path}")
    print("rows per table:", manifest["tables"], "| total", manifest["total_rows"])
    print("sha256 of content:", manifest["sha256"])
