"""Подписка устройства на push-уведомления (Web Push). Подключает сам пользователь в учётной записи."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import auth, notify, webpush
from ..db import get_db
from ..models import PushSubscription, User, now

router = APIRouter(prefix="/api/push", tags=["push"])
MAX_DEVICES = 10


class Keys(BaseModel):
    p256dh: str = Field(min_length=80, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    auth: str = Field(min_length=16, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")


class SubscriptionIn(BaseModel):
    endpoint: str = Field(max_length=1024)
    keys: Keys


@router.get("/key")
def server_key(user: User = Depends(auth.current_user)):
    return {"public_key": webpush.public_key()}


@router.get("/subscriptions")
def my_devices(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    return {"devices": db.scalar(select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == user.id))}


@router.post("/subscriptions")
def subscribe(data: SubscriptionIn, request: Request, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    if not webpush.allowed_endpoint(data.endpoint):
        raise HTTPException(422, "Адрес подписки не относится к известному push-сервису браузера")
    try:  # ключ браузера должен быть точкой кривой P-256 — иначе уведомление не зашифровать
        webpush.encrypt(b"check", data.keys.p256dh, data.keys.auth)
    except Exception:
        raise HTTPException(422, "Некорректные ключи подписки")
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint))
    if sub is None:
        if db.scalar(select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == user.id)) >= MAX_DEVICES:
            raise HTTPException(409, f"Уведомления включены на {MAX_DEVICES} устройствах — отключите на одном из них")
        sub = PushSubscription(endpoint=data.endpoint)
        db.add(sub)
    # адрес мог принадлежать другой учётной записи на том же устройстве — подписка переходит к текущей
    sub.user_id, sub.p256dh, sub.auth, sub.created_at = user.id, data.keys.p256dh, data.keys.auth, now()
    sub.user_agent = (request.headers.get("user-agent") or "")[:256]
    auth.audit(db, user, "push_subscribed", "user", user.id)
    db.commit()
    return {"ok": True}


@router.delete("/subscriptions")
def unsubscribe(endpoint: str = Query(max_length=1024), user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    db.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint, PushSubscription.user_id == user.id))
    auth.audit(db, user, "push_unsubscribed", "user", user.id)
    db.commit()
    return {"ok": True}


@router.post("/test")
def test_push(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    if not notify.enqueue_push(db, user.id, "Компас", "Уведомления работают", "/", "test"):
        raise HTTPException(409, "Уведомления не включены ни на одном устройстве")
    db.commit()
    return {"ok": True, "note": "Уведомление придёт в течение нескольких секунд"}
