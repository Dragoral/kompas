"""Аутентификация, авторизация, журнал безопасности.

* Пароли — Argon2id (параметры не ниже OWASP Password Storage Cheat Sheet).
* Сессии — непрозрачные 256-битные токены; в БД — только SHA-256. Абсолютный
  TTL + таймаут бездействия, отзыв при выходе, смене пароля и блокировке.
* 2FA (TOTP, RFC 6238) — обязательна для врачей и администраторов в production.
* SSE: EventSource не умеет заголовки, поэтому вместо токена в URL —
  одноразовый тикет на 60 секунд (токен не попадает в логи прокси).
* Защита от перебора: блокировка учётной записи после 5 ошибок на 15 минут,
  проверка «пустого» хеша для несуществующих логинов (одинаковое время ответа).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .crypto import new_token, token_hash
from .db import SessionLocal, WriteSession, defer_write, get_db
from .models import Alert, AuditLog, AuthSession, Patient, StreamTicket, User, now

SESSION_TTL = timedelta(hours=int(os.getenv("SESSION_TTL_HOURS", "12")))
IDLE_TIMEOUT = timedelta(minutes=int(os.getenv("SESSION_IDLE_MIN", "60")))
MAX_FAILED = 5
LOCKOUT = timedelta(minutes=15)
REQUIRE_MFA = os.getenv("REQUIRE_MFA", "0") == "1"  # в демо выключено, в production — включено

# OWASP: Argon2id, m=19 MiB, t=2, p=1 — минимум; берём с запасом
_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
_DUMMY_HASH = _ph.hash(secrets.token_urlsafe(16))
_bearer = HTTPBearer(auto_error=False)

# Небольшой список самых частых паролей (NIST 800-63B: проверка по словарю скомпрометированных)
_COMMON = {"123456", "password", "12345678", "qwerty", "123456789", "12345", "1234567890", "1q2w3e4r",
           "qwerty123", "111111", "000000", "password1", "йцукен", "пароль", "1234567", "qwertyuiop"}


def hash_password(p: str) -> str:
    return _ph.hash(p)


def check_password_policy(p: str, login: str = "") -> None:
    if len(p) < 10:
        raise HTTPException(422, "Пароль должен быть не короче 10 символов")
    if p.lower() in _COMMON or (login and login.lower() in p.lower()):
        raise HTTPException(422, "Пароль слишком простой или содержит логин")


def verify_password(p: str, h: str | None) -> bool:
    try:
        return _ph.verify(h or _DUMMY_HASH, p) and h is not None
    except (VerificationError, InvalidHashError):
        return False


# --- сессии ---------------------------------------------------------------
def create_session(db: Session, user: User, request: Request | None, mfa_passed: bool) -> str:
    token = new_token()
    db.add(AuthSession(
        user_id=user.id, token_hash=token_hash(token), expires_at=now() + SESSION_TTL, mfa_passed=mfa_passed,
        user_agent=(request.headers.get("user-agent", "")[:256] if request else None),
        ip=client_ip(request),
    ))
    return token


def revoke_all(db: Session, user_id: int) -> None:
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))):
        s.revoked_at = now()


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def _session_user(token: str | None, db: Session) -> tuple[User, AuthSession]:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация")
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    t = now()
    if not s or s.revoked_at or s.expires_at < t or s.last_seen_at + IDLE_TIMEOUT < t:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия недействительна или истекла")
    user = db.get(User, s.user_id)
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Учётная запись отключена")
    if REQUIRE_MFA and user.role in ("doctor", "admin") and not s.mfa_passed:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется второй фактор")
    if (t - s.last_seen_at).total_seconds() > 60:  # не пишем в БД на каждый запрос
        sid = s.id
        defer_write(db, lambda w: w.execute(update(AuthSession).where(AuthSession.id == sid).values(last_seen_at=t)))
    return user, s


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    return _session_user(cred.credentials if cred else None, db)[0]


def current_session(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> AuthSession:
    return _session_user(cred.credentials if cred else None, db)[1]


def require(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user
    return dep


# --- одноразовые тикеты для SSE (в БД: работают при нескольких процессах) ----
def issue_ticket(db: Session, user: User) -> str:
    t = secrets.token_urlsafe(24)
    db.add(StreamTicket(token_hash=token_hash(t), user_id=user.id, expires_at=now() + timedelta(seconds=60)))
    db.commit()
    return t


def redeem_ticket(ticket: str, db: Session) -> User:
    with WriteSession() as w:  # одноразовый: удаление атомарно
        res = w.execute(delete(StreamTicket).where(StreamTicket.token_hash == token_hash(ticket), StreamTicket.expires_at >= now())
                        .returning(StreamTicket.user_id))
        uid = res.scalar()
        w.commit()
    if uid is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Тикет недействителен")
    user = db.get(User, uid)
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Учётная запись отключена")
    return user


# --- TOTP -------------------------------------------------------------------
def totp_ok(user: User, code: str | None) -> bool:
    if not user.totp_secret:
        return False
    return bool(code) and pyotp.TOTP(user.totp_secret).verify(code, valid_window=1)


# --- доступ к данным пациента ---------------------------------------------
def patient_for(user: User, patient_id: int, db: Session) -> Patient:
    """Лечащий врач — свои пациенты; дежурный — только пациенты с эскалацией на него;
    пациент — только своя карта. Каждое обращение к карте пишется в журнал."""
    p = db.get(Patient, patient_id)
    if not p or p.erased_at:
        raise HTTPException(404, "Пациент не найден")
    if user.role == "patient" and p.user_id == user.id:
        return p
    if user.role == "doctor" and p.doctor_id == user.id:
        return p
    if user.role == "doctor" and user.is_duty and db.scalar(
            select(Alert.id).where(Alert.patient_id == p.id, Alert.escalated_to == user.id).limit(1)):
        return p
    audit(db, user, "access_denied", "patient", p.id, patient_id=p.id)
    db.commit()
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к данным пациента")


def own_patient(user: User, db: Session) -> Patient:
    p = db.scalar(select(Patient).where(Patient.user_id == user.id))
    if not p or p.erased_at:
        raise HTTPException(404, "Карточка пациента не найдена")
    return p


# --- журнал ---------------------------------------------------------------
def audit(db: Session, user: User | None, action: str, entity: str, entity_id: int | None = None,
          patient_id: int | None = None, ip: str | None = None, **details) -> None:
    """Только идентификаторы и структурированные поля — без ПДн и свободного текста."""
    row = dict(user_id=user.id if user else None, action=action, entity=entity, entity_id=entity_id,
               patient_id=patient_id, details=details, ip=ip, created_at=now())
    defer_write(db, lambda w: w.add(AuditLog(**row)))


def _canonical(r: AuditLog) -> bytes:
    return json.dumps([r.id, r.user_id, r.action, r.entity, r.entity_id, r.patient_id, r.details, r.ip,
                       r.created_at.isoformat()], ensure_ascii=False, sort_keys=True, default=str).encode()


_seal_lock = threading.Lock()


def seal_audit() -> int:
    """Сцепить новые записи журнала. Выполняется одним потоком — гонок нет."""
    with _seal_lock, WriteSession() as db:
        last = db.scalar(select(AuditLog).where(AuditLog.hash.is_not(None)).order_by(AuditLog.id.desc()).limit(1))
        prev = last.hash if last else "0" * 64
        rows = db.scalars(select(AuditLog).where(AuditLog.hash.is_(None)).order_by(AuditLog.id)).all()
        for r in rows:
            r.prev_hash = prev
            r.hash = hashlib.sha256(prev.encode() + _canonical(r)).hexdigest()
            prev = r.hash
        db.commit()
        return len(rows)


def verify_audit(db: Session) -> dict:
    prev, n = "0" * 64, 0
    for r in db.scalars(select(AuditLog).where(AuditLog.hash.is_not(None)).order_by(AuditLog.id)):
        expected = hashlib.sha256(prev.encode() + _canonical(r)).hexdigest()
        if r.prev_hash != prev or r.hash != expected:
            return {"ok": False, "broken_at_id": r.id, "checked": n}
        prev, n = r.hash, n + 1
    return {"ok": True, "checked": n, "head": prev}
