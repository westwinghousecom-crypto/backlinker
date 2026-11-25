import importlib.util
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core import backup
from app.core.config import get_settings
from fake_appwrite import FakeTablesDB

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


export_script, restore_script = load_script("backup_export"), load_script("restore_backup")
KEY = Fernet.generate_key().decode()
TOKEN_BLOB = "gAAAAABfake-refresh-token-ciphertext-under-TOKEN_ENCRYPTION_KEY"
T0 = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
TABLE_IDS = {name: getattr(get_settings(), attr) for name, attr in backup.BACKUP_TABLES.items()}


def seeded() -> FakeTablesDB:
    db = FakeTablesDB()
    db.seed("urls", "u1", {"user_id": "alice", "url": "https://alice-secret-site.example/page", "status": "completed"}, T0)
    db.seed("urls", "u2", {"user_id": "bob", "url": "https://bob.example/x", "status": "pending"}, T0)
    db.seed("check_batches", "cb1", {"user_id": "alice", "target": "https://alice-secret-site.example", "total": 2}, T0)
    db.seed("checks", "c1", {"user_id": "alice", "batch_id": "cb1", "url": "https://x.example", "result": '{"verdict":"eligible"}'}, T0)
    db.seed("batch_sharing", "cb1", {"user_id": "alice", "public_feed": False}, T0)
    db.seed("google_connections", "alice", {"user_id": "alice", "google_email": "alice-private@gmail.com", "refresh_token_enc": TOKEN_BLOB,
                                            "status": "active", "scopes": "webmasters.readonly"}, T0)
    db.seed("gsc_targets", "t1", {"user_id": "alice", "url": "https://alice-secret-site.example/a", "status": "pending"}, T0)
    db.seed("gsc_history", "h1", {"user_id": "alice", "target_id": "t1", "status": "indexed"}, T0)
    db.seed("google_quota", "q1", {"count": 7}, T0)  # not backed up
    db.seed("google_oauth_states", "s1", {"user_id": "alice"}, T0)  # not backed up
    return db


def snapshot(db):
    return {t: {i: dict(r.data) for i, r in rows.items()} for t, rows in db.tables.items()}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", KEY)
    get_settings.cache_clear()
    db = seeded()
    monkeypatch.setattr(export_script, "get_tables_db", lambda: db)
    monkeypatch.setattr(restore_script, "get_tables_db", lambda: db)
    yield db, tmp_path
    get_settings.cache_clear()


def do_export(tmp_path):
    return export_script.run(str(tmp_path / "backups"), now=datetime(2026, 11, 11, 8, 30, 15, tzinfo=timezone.utc))


def test_export_writes_a_dated_encrypted_file_and_manifest(env):
    db, tmp = env
    data_path, manifest_path, manifest = do_export(tmp)
    assert data_path.name == "quickindex-20261111-083015.json.enc" and manifest_path.name == "quickindex-20261111-083015.manifest.json"
    assert manifest["tables"] == {"urls": 2, "check_batches": 1, "checks": 1, "batch_sharing": 1, "google_connections": 1, "gsc_targets": 1, "gsc_history": 1}
    assert manifest["total_rows"] == 8 and re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"])
    assert "google_quota" not in manifest["tables"] and "google_oauth_states" not in manifest["tables"]
    assert json.loads(manifest_path.read_text()) == manifest


def test_the_backup_file_contains_no_plaintext_data_or_tokens(env):
    db, tmp = env
    data_path, manifest_path, _ = do_export(tmp)
    raw = data_path.read_bytes()
    for secret in (b"alice-secret-site", b"alice-private@gmail.com", TOKEN_BLOB.encode(), b"refresh", b"https://", b"bob.example", b"user_id"):
        assert secret not in raw, secret
    assert b"alice" not in manifest_path.read_bytes()  # the manifest holds counts and a hash, never rows


def test_round_trip_restores_identical_rows_with_owner_only_permissions(env):
    db, tmp = env
    data_path, manifest_path, manifest = do_export(tmp)
    original = snapshot(db)
    for t in list(TABLE_IDS.values()):
        db.tables[t].clear()
    assert all(db.count(t) == 0 for t in TABLE_IDS.values())

    payload = backup.open_backup(data_path.read_bytes(), KEY, manifest)
    report = backup.restore(db, "", TABLE_IDS, payload)
    assert all(c["created"] == manifest["tables"][name] for name, c in report.items())
    restored = snapshot(db)
    for table in TABLE_IDS.values():
        assert restored[table] == original[table], table  # same ids, same data (incl. the still-encrypted token blob)
    assert db.tables["urls"]["u1"].permissions == ['read("user:alice")'] and db.tables["google_connections"]["alice"].permissions == ['read("user:alice")']


def test_verify_detects_every_kind_of_damage(env):
    db, tmp = env
    data_path, manifest_path, manifest = do_export(tmp)
    blob = data_path.read_bytes()
    assert backup.open_backup(blob, KEY, manifest)["format"] == 1

    flipped = bytearray(blob)
    flipped[len(flipped) // 2] ^= 0x01  # one bit changed in the encrypted file
    with pytest.raises(backup.BackupError, match="modified|corrupt|wrong"):
        backup.open_backup(bytes(flipped), KEY, manifest)
    with pytest.raises(backup.BackupError, match="wrong BACKUP_ENCRYPTION_KEY"):
        backup.open_backup(blob, Fernet.generate_key().decode(), manifest)
    with pytest.raises(backup.BackupError, match="SHA-256"):
        backup.open_backup(blob, KEY, {**manifest, "sha256": "0" * 64})
    with pytest.raises(backup.BackupError, match="row counts"):
        backup.open_backup(blob, KEY, {**manifest, "tables": {**manifest["tables"], "urls": 99}})
    with pytest.raises(backup.BackupError, match="not set"):
        backup.open_backup(blob, "", manifest)
    with pytest.raises(backup.BackupError, match="not a valid"):
        backup.open_backup(blob, "not-a-key", manifest)


def test_key_rotation_old_key_still_opens_a_backup(env):
    db, tmp = env
    data_path, _, manifest = do_export(tmp)
    new = Fernet.generate_key().decode()
    assert backup.open_backup(data_path.read_bytes(), f"{new},{KEY}", manifest)["tables"]["urls"]


def test_the_export_script_refuses_to_run_without_a_key(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setattr(export_script, "get_tables_db", lambda: pytest.fail("must not read Appwrite without a key"))
    with pytest.raises(SystemExit, match="BACKUP_ENCRYPTION_KEY"):
        export_script.run(str(tmp_path))
    assert not list(tmp_path.glob("**/*.enc"))
    get_settings.cache_clear()


def test_restore_does_not_overwrite_rows_changed_after_the_backup_unless_forced(env):
    db, tmp = env
    data_path, _, manifest = do_export(tmp)
    payload = backup.open_backup(data_path.read_bytes(), KEY, manifest)
    db.update_row("", "urls", "u1", {"status": "failed"})  # changed after the backup: its updatedat is now > the backup's
    before = snapshot(db)
    report = backup.restore(db, "", TABLE_IDS, payload)
    assert report["urls"] == {"created": 0, "updated": 0, "unchanged": 1, "kept_newer": 1} and snapshot(db) == before
    forced = backup.restore(db, "", TABLE_IDS, payload, force=True)
    assert forced["urls"]["updated"] == 1 and db.tables["urls"]["u1"].data["status"] == "completed"


def test_restore_fills_gaps_without_touching_matching_rows(env):
    db, tmp = env
    data_path, _, manifest = do_export(tmp)
    payload = backup.open_backup(data_path.read_bytes(), KEY, manifest)
    del db.tables["urls"]["u2"]
    report = backup.restore(db, "", TABLE_IDS, payload)
    assert report["urls"] == {"created": 1, "updated": 0, "unchanged": 1, "kept_newer": 0} and "u2" in db.tables["urls"]


def test_dry_run_reports_but_writes_nothing(env):
    db, tmp = env
    data_path, _, manifest = do_export(tmp)
    payload = backup.open_backup(data_path.read_bytes(), KEY, manifest)
    for t in TABLE_IDS.values():
        db.tables[t].clear()
    report = backup.restore(db, "", TABLE_IDS, payload, dry_run=True)
    assert report["urls"]["created"] == 2 and all(db.count(t) == 0 for t in TABLE_IDS.values())


def test_export_paginates_past_one_page(env):
    db, tmp = env
    for i in range(230):
        db.seed("gsc_history", f"many-{i}", {"user_id": "alice", "n": i}, T0)
    _, _, manifest = do_export(tmp)
    assert manifest["tables"]["gsc_history"] == 231


def test_restore_script_verify_dry_run_and_restore_modes(env, capsys):
    db, tmp = env
    data_path, _, manifest = do_export(tmp)
    assert restore_script.main([str(data_path), "--verify"]) == 0 and "SHA-256 matches" in capsys.readouterr().out
    for t in TABLE_IDS.values():
        db.tables[t].clear()
    assert restore_script.main([str(data_path), "--dry-run"]) == 0
    assert "DRY RUN" in capsys.readouterr().out and db.count("urls") == 0
    assert restore_script.main([str(data_path), "--restore"]) == 0
    assert db.count("urls") == 2 and "RESTORED" in capsys.readouterr().out


def test_restore_script_verify_fails_on_a_tampered_file_and_writes_nothing(env):
    db, tmp = env
    data_path, _, _ = do_export(tmp)
    blob = bytearray(data_path.read_bytes())
    blob[40] ^= 0xFF
    data_path.write_bytes(bytes(blob))
    before = snapshot(db)
    with pytest.raises(SystemExit, match="VERIFY FAILED"):
        restore_script.main([str(data_path), "--restore"])
    assert snapshot(db) == before


def test_restore_script_needs_the_manifest(env):
    db, tmp = env
    data_path, manifest_path, _ = do_export(tmp)
    manifest_path.unlink()
    with pytest.raises(SystemExit, match="manifest not found"):
        restore_script.main([str(data_path), "--verify"])


def test_backups_folder_is_git_ignored_and_the_key_is_documented():
    root = Path(__file__).resolve().parents[1]
    assert "backups/" in (root / ".gitignore").read_text().splitlines()
    example = (root / ".env.example").read_text()
    assert "BACKUP_ENCRYPTION_KEY=" in example and not re.search(r"BACKUP_ENCRYPTION_KEY=\S", example)
