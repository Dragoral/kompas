"""Фоновые задачи. При нескольких рабочих процессах каждую задачу выполняет
только держатель «аренды» в БД. Каждый запуск отмечается в реестре
компонентов (успех/ошибка, длительность) — его видно в /api/ready и в статусе
системы для администратора. Сбой задачи не останавливает цикл.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from . import auth, backup, bus as bus_mod, notify, observability
from .bus import doctor_channel
from .config import BASE_DIR, ESCALATION_CHECK_SEC
from .crypto import vault
from .db import IS_SQLITE, SessionLocal, WriteSession
from .engine import alerts, knowledge
from .models import Alert, Event, Lease, Message, Patient, StreamTicket, User, now

log = logging.getLogger("kompas.jobs")
RETENTION_MESSAGES_DAYS = 365  # сопутствующие материалы — 1 год (193н п. 51)
HOLDER = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def holds_lease(name: str, ttl_sec: int = 90) -> bool:
    with WriteSession() as db:
        t = now()
        r = db.execute(update(Lease).where(Lease.name == name, (Lease.expires_at < t) | (Lease.holder == HOLDER))
                       .values(holder=HOLDER, expires_at=t + timedelta(seconds=ttl_sec)))
        if r.rowcount:
            db.commit()
            return True
        try:
            db.add(Lease(name=name, holder=HOLDER, expires_at=t + timedelta(seconds=ttl_sec)))
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False


def escalation() -> int:
    """Критический алерт без подтверждения дольше порога -> дежурному врачу (193н п. 44, 46 «л»)."""
    n = 0
    with WriteSession() as db:
        kb = knowledge.get(db)
        if not notify.policy(kb).get("duty_service"):
            return 0
        t = now()
        pending = db.scalars(select(Alert).where(Alert.status == "new", Alert.escalate_after_min.is_not(None),
                                                 Alert.escalated_to.is_(None))).all()
        for a in pending:
            if a.created_at + timedelta(minutes=a.escalate_after_min) > t:
                continue
            duty = db.scalar(select(User).where(User.is_duty.is_(True), User.active.is_(True), User.id != a.doctor_id))
            if not duty:
                observability.report_problem("escalation", f"alert:{a.id}", "нет активного дежурного врача", "warning")
                continue
            a.escalated_to, a.escalated_at = duty.id, t
            auth.audit(db, None, "alert_escalated", "alert", a.id, patient_id=a.patient_id, to_user=duty.id)
            bus_mod.enqueue(db, doctor_channel(duty.id), "alert", {**alerts.alert_event(a), "escalated": True})
            notify.enqueue_escalation(db, kb, a, db.get(Patient, a.patient_id), duty)
            a.notified = (a.notified or []) + ["дежурная служба (нет подтверждения от лечащего врача)"]
            db.commit()
            n += 1
    return n


def maintenance() -> None:
    """Сроки хранения, очистка служебных таблиц, крипто-шреддинг, запечатывание журнала."""
    auth.seal_audit()
    with WriteSession() as db:
        t = now()
        db.execute(delete(Message).where(Message.created_at < t - timedelta(days=RETENTION_MESSAGES_DAYS)))
        db.execute(delete(Event).where(Event.created_at < t - timedelta(days=2)))
        db.execute(delete(StreamTicket).where(StreamTicket.expires_at < t))
        # Отзыв согласия: по истечении срока — крипто-шреддинг (152-ФЗ ст. 21 ч. 5)
        for p in db.scalars(select(Patient).where(Patient.erase_after.is_not(None), Patient.erase_after < t, Patient.erased_at.is_(None))):
            vault.shred(db, p.id)
            p.full_name_enc = p.birth_date_enc = p.contacts_enc = p.name_bidx = None
            p.erased_at, p.monitoring_active = t, False
            auth.audit(db, None, "patient_crypto_shredded", "patient", p.id, patient_id=p.id)
        db.commit()
    auth.seal_audit()
    with SessionLocal() as db:  # якорь: голова цепочки во внешний журнал (обнаружение усечения)
        head = auth.verify_audit(db).get("head")
    if head:
        (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
        with open(BASE_DIR / "data" / "audit_anchor.log", "a", encoding="utf-8") as f:
            f.write(f"{now().isoformat()} {head}\n")


def notifications() -> None:
    with WriteSession() as db:
        notify.send_pending(db)


def backups() -> None:
    if IS_SQLITE:  # для PostgreSQL — pg_dump/архив WAL средствами инфраструктуры
        backup.create()


async def _loop(name: str, fn, period: float):
    while True:
        t0 = time.perf_counter()
        try:
            if await asyncio.to_thread(holds_lease, name, int(period) + 60):
                await asyncio.to_thread(fn)
                observability.task_ran(name, True, (time.perf_counter() - t0) * 1000)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("background task %s failed", name, extra={"component": name})
            observability.task_ran(name, False, (time.perf_counter() - t0) * 1000, f"{e.__class__.__name__}: {e}")
        await asyncio.sleep(period)


SCHEDULE = {
    "escalation": (escalation, ESCALATION_CHECK_SEC),
    "maintenance": (maintenance, 60),
    "notifications": (notifications, 5),
    "backups": (backups, int(os.getenv("BACKUP_INTERVAL_MIN", "15")) * 60),
}


def start() -> list[asyncio.Task]:
    return [asyncio.create_task(_loop(name, fn, period)) for name, (fn, period) in SCHEDULE.items()]
