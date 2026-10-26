"""Encrypted PostgreSQL backups plus an isolated restore drill.

The dump is encrypted with the application's backup-v1 AES-256-GCM key; do not
store the master key beside the encrypted dumps. The drill creates a temporary
empty database on the same PostgreSQL instance, restores the dump there, counts
its public tables, then drops the temporary database.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import BASE_DIR, DATABASE_URL
from .crypto import vault

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", BASE_DIR / "data" / "backups"))
BACKUP_KEEP = max(1, int(os.getenv("BACKUP_KEEP", "96")))
DRILL_FILE = BASE_DIR / "data" / "backup_drill.json"


def _key(kid: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"backup-v1").derive(vault.keks[kid])


def _url(database: str | None = None):
    url = make_url(DATABASE_URL)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("backup_postgres требует PostgreSQL DATABASE_URL")
    if database is not None:
        url = url.set(database=database)
    # Password is passed through PGPASSWORD, not argv/connection URI.
    return url.set(drivername="postgresql", password=None)


def _env() -> dict[str, str]:
    env = os.environ.copy()
    password = make_url(DATABASE_URL).password
    if password:
        env["PGPASSWORD"] = password
    return env


def _dsn(database: str | None = None) -> str:
    return _url(database).render_as_string(hide_password=False)


def _pg_dump() -> bytes:
    result = subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--dbname", _dsn()],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env(), timeout=3600,
    )
    return result.stdout


def _encrypt(raw: bytes, name: str) -> tuple[bytes, dict]:
    kid = vault.kid
    nonce = os.urandom(12)
    encrypted = nonce + AESGCM(_key(kid)).encrypt(nonce, raw, name.encode())
    manifest = {
        "file": name, "engine": "postgresql", "kid": kid,
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return encrypted, manifest


def _decrypt(path: Path) -> tuple[bytes, dict]:
    manifest = json.loads(Path(str(path) + ".json").read_text(encoding="utf-8"))
    if manifest.get("engine") != "postgresql":
        raise ValueError("Ожидался PostgreSQL-бэкап")
    data = path.read_bytes()
    raw = AESGCM(_key(manifest["kid"])).decrypt(data[:12], data[12:], path.name.encode())
    if not secrets.compare_digest(hashlib.sha256(raw).hexdigest(), manifest["sha256"]):
        raise ValueError("Контрольная сумма бэкапа не совпадает")
    return raw, manifest


def create() -> dict:
    t0 = time.perf_counter()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    raw = _pg_dump()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"kompas-postgres-{stamp}.dump.enc"
    encrypted, manifest = _encrypt(raw, name)
    target = BACKUP_DIR / name
    target.write_bytes(encrypted)
    manifest["duration_ms"] = round((time.perf_counter() - t0) * 1000)
    Path(str(target) + ".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    backups = sorted(BACKUP_DIR.glob("kompas-postgres-*.dump.enc"))
    for old in backups[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)
        Path(str(old) + ".json").unlink(missing_ok=True)
    return manifest


def restore(backup_file: Path, target_database: str) -> dict:
    """Restore an encrypted dump to an explicitly named target database.

    WARNING: pg_restore --clean removes conflicting objects in target_database.
    The target database must be intentionally supplied by the operator.
    """
    if not target_database or target_database == make_url(DATABASE_URL).database:
        raise ValueError("Для восстановления укажите отдельную целевую БД, не исходную")
    t0 = time.perf_counter()
    raw, manifest = _decrypt(backup_file)
    with tempfile.NamedTemporaryFile(prefix="kompas-restore-", suffix=".dump") as fp:
        fp.write(raw)
        fp.flush()
        subprocess.run(
            ["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-acl", "--exit-on-error",
             "--dbname", _dsn(target_database), fp.name],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env(), timeout=3600,
        )
    return {"restored_from": backup_file.name, "target_database": target_database,
            "duration_ms": round((time.perf_counter() - t0) * 1000), "sha256": manifest["sha256"]}


def _counts(database: str) -> dict[str, int]:
    url = make_url(DATABASE_URL)
    with psycopg.connect(_dsn(database), password=url.password) as conn:
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename").fetchall()
        counts: dict[str, int] = {}
        for (table,) in tables:
            # Identifier is safely quoted; table names come from pg_catalog.
            counts[table] = int(conn.execute(sql.SQL("SELECT COUNT(*) FROM public.{}").format(sql.Identifier(table))).fetchone()[0])
        return counts


def drill() -> dict:
    """Perform a real restore into a temporary DB; remove it even on failure."""
    t0 = time.perf_counter()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = create()
    archive = BACKUP_DIR / backup["file"]
    source = make_url(DATABASE_URL)
    temp_db = f"kompas_drill_{secrets.token_hex(5)}"
    created = False
    result: dict = {"checked_at": datetime.now(timezone.utc).isoformat(), "engine": "postgresql",
                    "backup_ms": backup.get("duration_ms"), "db_bytes": backup.get("bytes"),
                    "encrypted": True, "backup_file": backup["file"]}
    try:
        # CREATE DATABASE must execute outside a transaction. The Compose role
        # owns the cluster; for managed PostgreSQL grant CREATEDB to the backup role.
        with psycopg.connect(_dsn("postgres"), password=source.password, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(temp_db)))
        created = True
        restored = restore(archive, temp_db)
        counts = _counts(temp_db)
        if not counts or "users" not in counts or "patients" not in counts:
            raise RuntimeError("Restore завершился, но обязательные таблицы users/patients отсутствуют")
        result.update({"restore_ok": True, "restore_ms": restored["duration_ms"], "rto_ms": round((time.perf_counter() - t0) * 1000),
                       "table_count": len(counts), "rows": counts,
                       "rpo_note": f"Максимальная потеря при отказе — интервал резервирования ({os.getenv('BACKUP_INTERVAL_MIN', '15')} мин), если последнее задание завершилось успешно."})
    except Exception as exc:
        result.update({"restore_ok": False, "error": type(exc).__name__, "detail": str(exc)[:500],
                       "rto_ms": round((time.perf_counter() - t0) * 1000)})
        raise
    finally:
        if created:
            try:
                with psycopg.connect(_dsn("postgres"), password=source.password, autocommit=True) as conn:
                    conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(temp_db)))
            except Exception:
                # The operational error remains visible in application logs; do not hide it.
                pass
        DRILL_FILE.parent.mkdir(parents=True, exist_ok=True)
        DRILL_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Encrypted PostgreSQL backup/restore")
    parser.add_argument("cmd", choices=("create", "drill", "restore"))
    parser.add_argument("file", nargs="?")
    parser.add_argument("--to", help="existing target database for restore; never restored to source DB")
    args = parser.parse_args()
    if args.cmd == "create":
        output = create()
    elif args.cmd == "drill":
        output = drill()
    else:
        if not args.file or not args.to:
            parser.error("restore requires encrypted backup file and --to TARGET_DATABASE")
        output = restore(Path(args.file), args.to)
    print(json.dumps(output, ensure_ascii=False, indent=2))
