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

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from . import auth, backup, bus as bus_mod, notify, observability, services
from .bus import doctor_channel
from .config import BASE_DIR, ESCALATION_CHECK_SEC
from .crypto import vault
from .db import IS_SQLITE, SessionLocal, WriteSession
from .engine import alerts, knowledge
from .models import (Alert, DiaryEntry, DoseLog, Event, Lease, Message, Patient, Prescription, ScaleAssignment,
                     StreamTicket, User, now)

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
            alerts.push_alert(db, duty.id, a, db.get(Patient, a.patient_id), escalated=True)
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
        for rx in db.scalars(select(Prescription).where(Prescription.status == "active")):
            services.extend_dose_schedule(db, rx)
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


REMINDER_DEFAULTS = {"dose_window_min": 15, "scales_at": "10:00", "diary_at": "20:00", "quiet_after": "22:00"}


def reminders() -> int:
    """Push-напоминания пациентам на дистанционном наблюдении: приём препарата, шкалы на сегодня,
    дневник. Каждое — не чаще одного раза (отметка в БД), только при действующем согласии."""
    n = 0
    with WriteSession() as db:
        kb = knowledge.get(db)
        cfg = {**REMINDER_DEFAULTS, **(kb["dictionary"].get("monitoring_plan", {}).get("reminders") or {})}
        local = notify.local_time(notify.policy(kb))
        hm, today, t = local.strftime("%H:%M"), local.date(), now()
        eligible = select(Patient.id).where(Patient.monitoring_active.is_(True), Patient.erased_at.is_(None),
                                            Patient.consent_at.is_not(None), Patient.consent_withdrawn_at.is_(None))
        doses = db.scalars(select(DoseLog).join(Prescription, Prescription.id == DoseLog.prescription_id).where(
            DoseLog.status == "pending", DoseLog.reminded_at.is_(None), Prescription.status == "active",
            DoseLog.scheduled_for <= t, DoseLog.scheduled_for >= t - timedelta(minutes=int(cfg["dose_window_min"])),
            DoseLog.patient_id.in_(eligible))).all()
        for d in doses:
            d.reminded_at = t
            n += notify.enqueue_push(db, db.get(Patient, d.patient_id).user_id, "Компас", "Время принять лекарство",
                                     "/me", f"dose-{d.id}", "high")
        if cfg["scales_at"] <= hm < cfg["quiet_after"]:
            due: dict[int, list[ScaleAssignment]] = {}
            for a in db.scalars(select(ScaleAssignment).where(
                    ScaleAssignment.active.is_(True), ScaleAssignment.next_due <= today, ScaleAssignment.patient_id.in_(eligible),
                    or_(ScaleAssignment.reminded_on.is_(None), ScaleAssignment.reminded_on < today))):
                due.setdefault(a.patient_id, []).append(a)
            for pid, items in due.items():
                for a in items:
                    a.reminded_on = today
                n += notify.enqueue_push(db, db.get(Patient, pid).user_id, "Компас", "Пора заполнить опросник на сегодня",
                                         "/me", "scales")
        if cfg["diary_at"] <= hm < cfg["quiet_after"]:
            done = select(DiaryEntry.patient_id).where(DiaryEntry.day == today)
            for p in db.scalars(select(Patient).where(Patient.id.in_(eligible), Patient.id.not_in(done),
                                                      or_(Patient.diary_reminded_on.is_(None), Patient.diary_reminded_on < today))):
                p.diary_reminded_on = today
                n += notify.enqueue_push(db, p.user_id, "Компас", "Отметьте самочувствие в дневнике", "/me/diary", "diary")
        db.commit()
    return n


def backups() -> None:
    if IS_SQLITE:
        backup.create()
    else:
        from . import backup_postgres
        backup_postgres.create()


def backup_drill() -> None:
    if IS_SQLITE:
        backup.drill()
    else:
        from . import backup_postgres
        backup_postgres.drill()


async def _loop(name: str, fn, period: float, initial_delay: float = 0):
    # Long-running backups and restore drills must not execute during every process
    # startup/reload; run them on their configured cadence instead.
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)
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
    "reminders": (reminders, 60),
    "backups": (backups, int(os.getenv("BACKUP_INTERVAL_MIN", "15")) * 60),
    "backup_drill": (backup_drill, int(os.getenv("BACKUP_DRILL_INTERVAL_HOURS", "168")) * 3600),
}


def start() -> list[asyncio.Task]:
    # Deterministic unit/integration tests exercise the jobs directly; do not run
    # long-lived schedulers against the same disposable SQLite database.
    if os.getenv("KOMPAS_DISABLE_BACKGROUND_JOBS", "0") == "1":
        return []
    tasks = []
    for name, (fn, period) in SCHEDULE.items():
        delay = period if name in {"backups", "backup_drill"} else 0
        tasks.append(asyncio.create_task(_loop(name, fn, period, initial_delay=delay)))
    return tasks
