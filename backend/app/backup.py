"""Резервное копирование и восстановление.

* Онлайн-снапшот БД (SQLite backup API — без остановки сервиса; для PostgreSQL —
  pg_dump/pg_basebackup + архив WAL, см. deploy/).
* Снапшот шифруется AES-256-GCM ключом, выведенным из мастер-ключа (HKDF,
  «backup-v1»): утечка файла бэкапа не раскрывает данные; AAD — имя файла.
* Манифест с SHA-256 открытого текста — проверка целостности при восстановлении.
* Ротация: хранится BACKUP_KEEP последних копий.
* Учебная тревога (drill): бэкап -> «потеря» БД -> восстановление в новый файл ->
  проверка (число записей, целостность журнала) -> время восстановления (RTO).

    python -m app.backup create
    python -m app.backup drill
    python -m app.backup restore data/backups/<file>.enc --to data/app.db   (сервис остановлен)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import BASE_DIR, DATABASE_URL
from .crypto import vault

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", BASE_DIR / "data" / "backups"))
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "96"))
TABLES = ["users", "patients", "patient_keys", "prescriptions", "scale_results", "diary_entries", "dose_logs",
          "adverse_events", "messages", "alerts", "clinical_actions", "documents", "knowledge", "audit_log"]


def _key(kid: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"backup-v1").derive(vault.keks[kid])


def _db_path() -> Path:
    if not DATABASE_URL.startswith("sqlite"):
        raise RuntimeError("Для PostgreSQL используйте pg_dump/архив WAL (deploy/backup.sh)")
    return Path(DATABASE_URL.removeprefix("sqlite:///"))


def _snapshot_bytes(src: Path) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "snap.db"
        s, d = sqlite3.connect(src), sqlite3.connect(tmp)
        try:
            s.backup(d)  # консистентный снапшот без остановки записи
        finally:
            d.close()
            s.close()
        return tmp.read_bytes()


def create() -> dict:
    t0 = time.perf_counter()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    raw = _snapshot_bytes(_db_path())
    name = f"kompas-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db.enc"
    nonce = os.urandom(12)
    blob = AESGCM(_key(vault.kid)).encrypt(nonce, raw, name.encode())
    (BACKUP_DIR / name).write_bytes(nonce + blob)
    manifest = {"file": name, "kid": vault.kid, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                "created_at": datetime.now(timezone.utc).isoformat(), "duration_ms": round((time.perf_counter() - t0) * 1000)}
    (BACKUP_DIR / (name + ".json")).write_text(json.dumps(manifest), encoding="utf-8")
    for old in sorted(BACKUP_DIR.glob("kompas-*.db.enc"))[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)
        Path(str(old) + ".json").unlink(missing_ok=True)
    return manifest


def restore(enc_file: Path, target: Path) -> dict:
    t0 = time.perf_counter()
    manifest = json.loads(Path(str(enc_file) + ".json").read_text(encoding="utf-8"))
    data = enc_file.read_bytes()
    raw = AESGCM(_key(manifest["kid"])).decrypt(data[:12], data[12:], enc_file.name.encode())
    if hashlib.sha256(raw).hexdigest() != manifest["sha256"]:
        raise ValueError("Контрольная сумма не совпадает — бэкап повреждён")
    tmp = target.with_suffix(".restoring")
    tmp.write_bytes(raw)
    for suffix in ("-wal", "-shm"):
        Path(str(target) + suffix).unlink(missing_ok=True)
    os.replace(tmp, target)  # атомарная замена
    return {"restored_from": enc_file.name, "duration_ms": round((time.perf_counter() - t0) * 1000)}


def _counts(path: Path) -> dict:
    c = sqlite3.connect(path)
    try:
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        c.close()


def drill() -> dict:
    """Учебная тревога: время восстановления и проверка, что ничего не потеряно."""
    src = _db_path()
    before = _counts(src)
    m = create()
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "restored.db"
        r = restore(BACKUP_DIR / m["file"], target)
        after = _counts(target)
        # проверка цепочки журнала на восстановленной копии
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from . import auth
        eng = create_engine(f"sqlite:///{target.as_posix()}")
        with Session(eng) as s:
            audit = auth.verify_audit(s)
        eng.dispose()
    rto_ms = round((time.perf_counter() - t0) * 1000)
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(), "backup_ms": m["duration_ms"], "restore_ms": r["duration_ms"],
        "rto_ms": rto_ms, "db_bytes": m["bytes"], "rows_match": before == after, "rows": after,
        "audit_chain_ok": audit["ok"], "encrypted": True,
        "rpo_note": f"Потеря при отказе диска — не более интервала резервирования ({os.getenv('BACKUP_INTERVAL_MIN', '15')} мин); "
                    "при сбое процесса подтверждённые транзакции сохраняются (WAL); данные, отправленные пациентом во время "
                    "недоступности сервера, остаются в офлайн-очереди устройства и досылаются без дублей (client_id)",
    }
    (BASE_DIR / "data" / "backup_drill.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["create", "restore", "drill"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--to")
    a = ap.parse_args()
    if a.cmd == "create":
        print(json.dumps(create(), ensure_ascii=False, indent=1))
    elif a.cmd == "drill":
        print(json.dumps(drill(), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(restore(Path(a.file), Path(a.to or _db_path())), ensure_ascii=False, indent=1))
