import sqlite3

import pytest
from conftest import pid

from app import auth
from app.crypto import Cipher, vault
from app.db import SessionLocal, engine
from app.models import AuditLog


def _raw_db_bytes() -> bytes:
    """Всё, что физически лежит в БД: файл SQLite или содержимое всех таблиц PostgreSQL."""
    if engine.url.get_backend_name() == "sqlite":
        path = engine.url.database
        c = sqlite3.connect(path)
        c.execute("PRAGMA wal_checkpoint(FULL)")
        c.close()
        return open(path, "rb").read()
    from sqlalchemy import text
    from app.db import Base
    chunks = []
    with engine.connect() as conn:
        for t in Base.metadata.sorted_tables:
            chunks += [r[0] for r in conn.execute(text(f"SELECT row_to_json(x)::text FROM {t.name} x"))]
    return " | ".join(chunks).encode()


def test_identifiers_and_free_text_encrypted_at_rest(client, tokens):
    raw = _raw_db_bytes()
    for plain in ("Соколова", "Лебедев", "Головокружение по утрам", "не хочу жить"):
        assert plain.encode() not in raw, plain


def test_ciphertext_bound_to_field_and_patient(client):
    with SessionLocal() as db:
        token = vault.seal(db, 1, "patients.full_name", "Иванов")
        db.commit()
        assert vault.open(db, 1, "patients.full_name", token) == "Иванов"
        with pytest.raises(Exception):
            vault.open(db, 2, "patients.full_name", token)  # чужой пациент
        with pytest.raises(Exception):
            vault.open(db, 1, "messages.text", token)  # другое поле
        kid, nonce, ct = Cipher.parse(token)
        tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
        with pytest.raises(Exception):
            vault.open(db, 1, "patients.full_name", tampered)


def test_session_tokens_stored_hashed(client, tokens):
    raw = _raw_db_bytes()
    token = tokens["patient1"]["Authorization"].split()[1]
    assert token.encode() not in raw


def test_logout_revokes(client):
    r = client.post("/api/auth/login", json={"login": "patient3", "password": "Kompas-demo-2026"}).json()
    h = {"Authorization": f"Bearer {r['token']}"}
    assert client.get("/api/auth/me", headers=h).status_code == 200
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_audit_chain_detects_tampering(client, tokens):
    auth.seal_audit()
    with SessionLocal() as db:
        assert auth.verify_audit(db)["ok"]
        row = db.query(AuditLog).filter(AuditLog.hash.is_not(None)).order_by(AuditLog.id).first()
        orig = row.action
        row.action = "nothing_happened"
        db.commit()
        res = auth.verify_audit(db)
        assert not res["ok"] and res["broken_at_id"] == row.id
        row.action = orig
        db.commit()
        assert auth.verify_audit(db)["ok"]


def test_crypto_shredding(client, tokens):
    from app.models import Patient
    with SessionLocal() as db:
        p = db.query(Patient).filter(Patient.code == "P-DEMO2").one()
        assert p.full_name.startswith("Кузнецов")
        vault.shred(db, p.id)
        db.commit()
        db.expire_all()
        assert db.get(Patient, p.id).full_name == "[данные удалены]"


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"


def test_totp_code_cannot_be_reused():
    import time
    import pyotp
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    step = int(time.time() // totp.interval)
    code = totp.generate_otp(step)
    assert auth._totp_step(secret, code, last_step=step - 1) == step
    assert auth._totp_step(secret, code, last_step=step) is None
    assert auth._totp_step(secret, "abc123", last_step=step - 1) is None
