"""Экстренные внешние уведомления (SMS) по критическим алертам.

Кого оповещать, решает политика клиники (справочник response_policy):
  * лечащий врач — только в его рабочее время;
  * вне рабочего времени — дежурная служба (врач с флагом «дежурный»), если она есть;
    лечащий врач увидит алерт первым при следующем входе;
  * доверенное лицо пациента — при выбранных алертах и только с отдельного письменного
    согласия пациента (323-ФЗ ст. 13 ч. 3, ст. 22 ч. 3; 152-ФЗ ст. 9); без диагноза;
  * сам пациент в любое время видит кризисный экран (это делает движок алертов).

Уведомления ставятся в очередь в той же транзакции, что и алерт; фоновый отправщик
доставляет их с повторами. Каждая попытка документируется (193н п. 46 «д»).
Провайдер: NOTIFY_PROVIDER = log (журнал сервера) | smsru (SMS.ru, SMSRU_API_ID).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Notification, TrustedContact, User, now

log = logging.getLogger("kompas.notify")
PROVIDER = os.getenv("NOTIFY_PROVIDER", "log")
MAX_ATTEMPTS = 3

DEFAULT_POLICY = {
    "timezone_offset_hours": 3,
    "working_hours": {"days": [1, 2, 3, 4, 5], "start": "09:00", "end": "18:00"},
    "duty_service": True,
    "trusted_contact": {"rules": [], "any_time": True, "sms_template": ""},
    "doctor_sms_template": "Компас: срочное уведомление по пациенту {patient_code}. Откройте кабинет врача.",
    "duty_sms_template": "Компас: ДЕЖУРНОМУ — срочное уведомление по пациенту {patient_code}.",
}


def policy(kb: dict) -> dict:
    return {**DEFAULT_POLICY, **kb.get("dictionary", {}).get("response_policy", {})}


def local_time(pol: dict, at: datetime | None = None) -> datetime:
    return (at or now()) + timedelta(hours=pol.get("timezone_offset_hours", 3))


def within_hours(hours: dict, local: datetime) -> bool:
    if local.isoweekday() not in hours.get("days", [1, 2, 3, 4, 5]):
        return False
    hm = local.strftime("%H:%M")
    return hours.get("start", "09:00") <= hm < hours.get("end", "18:00")


def _first_name(full_name: str | None) -> str:
    parts = (full_name or "").split()
    return parts[1] if len(parts) > 1 else (parts[0] if parts else "Ваш близкий")


def route_critical(db: Session, kb: dict, alert, patient, at: datetime | None = None) -> list[str]:
    """Поставить внешние уведомления по критическому алерту. Возвращает описание маршрута."""
    pol = policy(kb)
    local = local_time(pol, at)
    doctor = db.get(User, alert.doctor_id)
    fmt = {"patient_code": patient.code, "patient_first_name": _first_name(patient.full_name)}
    routed = []
    if doctor and within_hours(doctor.working_hours or pol["working_hours"], local):
        db.add(Notification(user_id=doctor.id, alert_id=alert.id, channel="sms", reason="attending",
                            text=pol["doctor_sms_template"].format(**fmt)))
        routed.append("лечащий врач (рабочее время)")
    else:
        routed.append("лечащий врач — вне рабочего времени, увидит алерт первым при входе")
        if pol.get("duty_service"):
            duty = db.scalar(select(User).where(User.is_duty.is_(True), User.active.is_(True), User.id != alert.doctor_id))
            if duty:
                alert.escalated_to, alert.escalated_at = duty.id, now()
                db.add(Notification(user_id=duty.id, alert_id=alert.id, channel="sms", reason="duty",
                                    text=pol["duty_sms_template"].format(**fmt)))
                routed.append("дежурная служба")
    tc_pol = pol.get("trusted_contact") or {}
    if alert.rule_id in tc_pol.get("rules", []) and tc_pol.get("sms_template"):
        if tc_pol.get("any_time", True) or within_hours(pol["working_hours"], local):
            for tc in db.scalars(select(TrustedContact).where(TrustedContact.patient_id == patient.id, TrustedContact.revoked_at.is_(None))):
                db.add(Notification(trusted_contact_id=tc.id, alert_id=alert.id, channel="sms", reason="trusted_contact",
                                    text=tc_pol["sms_template"].format(**fmt)))
                routed.append("доверенное лицо (по согласию пациента)")
    return routed


def enqueue_escalation(db: Session, kb: dict, alert, patient, duty: User) -> None:
    fmt = {"patient_code": patient.code, "patient_first_name": _first_name(patient.full_name)}
    db.add(Notification(user_id=duty.id, alert_id=alert.id, channel="sms", reason="escalation",
                        text=policy(kb)["duty_sms_template"].format(**fmt)))


def _send_log(phone: str | None, text: str) -> str:
    log.warning("SMS -> %s: %s", (phone or "нет номера")[:6] + "***", text)
    return "log"


def _send_smsru(phone: str | None, text: str) -> str:
    import httpx
    if not phone:
        raise RuntimeError("не указан телефон получателя")
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
    sender = PROVIDERS.get(PROVIDER, _send_log)
    n = 0
    for nt in db.scalars(select(Notification).where(Notification.status == "pending").order_by(Notification.id).limit(100)):
        if nt.user_id:
            u = db.get(User, nt.user_id)
            phone = u.phone if u and u.active else None
        else:
            tc = db.get(TrustedContact, nt.trusted_contact_id)
            phone = tc.phone if tc and not tc.revoked_at else None
        nt.attempts += 1
        nt.provider = PROVIDER
        try:
            nt.provider_id = sender(phone, nt.text)
            nt.status, nt.sent_at, nt.last_error = "sent", now(), None
            n += 1
        except Exception as e:  # сетевые ошибки, ошибки провайдера
            nt.last_error = str(e)[:250]
            if nt.attempts >= MAX_ATTEMPTS:
                nt.status = "failed"
                log.error("notification %s failed: %s", nt.id, nt.last_error)
        db.commit()
    return n
