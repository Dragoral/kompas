"""Экстренные внешние уведомления врачу (SMS / звонок) по критическим алертам.

Уведомление ставится в очередь в той же транзакции, что и алерт; фоновый
отправщик доставляет его с повторами (до MAX_ATTEMPTS). Каждая попытка
документируется. Текст не содержит медицинских сведений и ФИО — только
псевдоним пациента (Закон РФ № 3185-1, ст. 9; 152-ФЗ).

Провайдер выбирается переменной NOTIFY_PROVIDER:
  log   — запись в журнал сервера (по умолчанию, для демо и тестов);
  smsru — SMS через SMS.ru (SMSRU_API_ID); провайдер с серверами в РФ.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Notification, now

log = logging.getLogger("kompas.notify")
PROVIDER = os.getenv("NOTIFY_PROVIDER", "log")
MAX_ATTEMPTS = 3


def enqueue_for_alert(db: Session, alert, patient, user_id: int, escalated: bool = False) -> None:
    prefix = "Компас: ЭСКАЛАЦИЯ. " if escalated else "Компас: "
    text = f"{prefix}срочное уведомление по пациенту {patient.code}. Откройте кабинет врача."
    db.add(Notification(user_id=user_id, alert_id=alert.id, channel="sms", text=text))


def _send_log(phone: str | None, text: str) -> str:
    log.warning("SMS -> %s: %s", (phone or "нет номера")[:6] + "***", text)
    return "log"


def _send_smsru(phone: str | None, text: str) -> str:
    import httpx
    if not phone:
        raise RuntimeError("у врача не указан телефон")
    r = httpx.post("https://sms.ru/sms/send", timeout=10,
                   data={"api_id": os.environ["SMSRU_API_ID"], "to": phone, "msg": text, "json": 1})
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "OK":
        raise RuntimeError(str(body.get("status_text", "ошибка провайдера"))[:200])
    sms = next(iter(body.get("sms", {}).values()), {})
    if sms.get("status") != "OK":
        raise RuntimeError(str(sms.get("status_text", "ошибка отправки"))[:200])
    return str(sms.get("sms_id", ""))


PROVIDERS = {"log": _send_log, "smsru": _send_smsru}


def send_pending(db: Session) -> int:
    from .models import User
    sender = PROVIDERS.get(PROVIDER, _send_log)
    n = 0
    for nt in db.scalars(select(Notification).where(Notification.status == "pending").order_by(Notification.id).limit(100)):
        user = db.get(User, nt.user_id)
        nt.attempts += 1
        nt.provider = PROVIDER
        try:
            nt.provider_id = sender(user.phone if user else None, nt.text)
            nt.status, nt.sent_at, nt.last_error = "sent", now(), None
            n += 1
        except Exception as e:  # сетевые ошибки, ошибки провайдера
            nt.last_error = str(e)[:250]
            if nt.attempts >= MAX_ATTEMPTS:
                nt.status = "failed"
                log.error("notification %s failed: %s", nt.id, nt.last_error)
        db.commit()
    return n
