from __future__ import annotations

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..db import get_db
from ..models import AuthSession, User, now

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    login: str = Field(max_length=64)
    password: str = Field(max_length=256)
    totp: str | None = Field(None, max_length=8)


def user_dict(u: User) -> dict:
    return {"id": u.id, "login": u.login, "role": u.role, "full_name": u.full_name, "specialty": u.specialty,
            "is_duty": u.is_duty, "mfa_enabled": bool(u.totp_secret_enc)}


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = auth.client_ip(request)
    user = db.scalar(select(User).where(User.login == data.login.strip().lower()))
    t = now()
    if user and user.locked_until and user.locked_until > t:
        auth.audit(db, user, "login_locked", "user", user.id, ip=ip)
        db.commit()
        raise HTTPException(429, "Учётная запись временно заблокирована после неудачных попыток входа")
    ok = auth.verify_password(data.password, user.password_hash if user else None)
    if not ok or not user.active:
        if user:
            user.failed_logins += 1
            if user.failed_logins >= auth.MAX_FAILED:
                user.locked_until, user.failed_logins = t + auth.LOCKOUT, 0
            auth.audit(db, user, "login_failed", "user", user.id, ip=ip)
        else:
            auth.audit(db, None, "login_failed_unknown", "user", ip=ip)
        db.commit()
        raise HTTPException(401, "Неверный логин или пароль")

    mfa = False
    if user.totp_secret_enc:
        if not auth.totp_ok(user, data.totp):
            raise HTTPException(401, "Введите код из приложения-аутентификатора")
        mfa = True
    elif auth.REQUIRE_MFA and user.role in ("doctor", "admin"):
        raise HTTPException(403, "Для врача требуется подключить второй фактор")

    user.failed_logins, user.locked_until = 0, None
    token = auth.create_session(db, user, request, mfa)
    auth.audit(db, user, "login", "user", user.id, ip=ip, mfa=mfa)
    db.commit()
    return {"token": token, "user": user_dict(user), "expires_in": int(auth.SESSION_TTL.total_seconds())}


@router.post("/logout")
def logout(s: AuthSession = Depends(auth.current_session), db: Session = Depends(get_db)):
    s = db.merge(s)
    s.revoked_at = now()
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(auth.current_user)):
    return user_dict(user)


class PasswordIn(BaseModel):
    old_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


@router.post("/password")
def change_password(data: PasswordIn, request: Request, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    user = db.merge(user)
    if not auth.verify_password(data.old_password, user.password_hash):
        raise HTTPException(401, "Неверный текущий пароль")
    auth.check_password_policy(data.new_password, user.login)
    user.password_hash, user.password_changed_at = auth.hash_password(data.new_password), now()
    auth.revoke_all(db, user.id)  # выход на всех устройствах
    auth.audit(db, user, "password_changed", "user", user.id, ip=auth.client_ip(request))
    db.commit()
    return {"ok": True, "relogin": True}


@router.post("/mfa/setup")
def mfa_setup(user: User = Depends(auth.current_user)):
    """Секрет сохраняется только после подтверждения кодом (/mfa/confirm)."""
    secret = pyotp.random_base32()
    return {"secret": secret, "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(name=user.login, issuer_name="Компас")}


class MfaConfirmIn(BaseModel):
    secret: str = Field(min_length=16, max_length=64)
    code: str = Field(min_length=6, max_length=8)


@router.post("/mfa/confirm")
def mfa_confirm(data: MfaConfirmIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    if not pyotp.TOTP(data.secret).verify(data.code, valid_window=1):
        raise HTTPException(422, "Неверный код")
    user = db.merge(user)
    user.totp_secret = data.secret
    auth.audit(db, user, "mfa_enabled", "user", user.id)
    db.commit()
    return {"ok": True}


@router.post("/stream-ticket")
def stream_ticket(user: User = Depends(auth.current_user)):
    return {"ticket": auth.issue_ticket(user)}
