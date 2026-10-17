"""Приём данных от пациента (дистанционное наблюдение, 193н п. 46 «б», «г», «д»).

* Идемпотентность по client_id: офлайн-очередь PWA может повторять отправку —
  дублей нет, критичные данные не теряются при сбоях связи.
* Данные принимаются только при действующем согласии на обработку ПДн и
  активном дистанционном наблюдении, назначенном врачом после очного приёма.
* Время получения фиксируется сервером (документирование факта получения).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .bus import doctor_channel, patient_channel
from .engine import alerts, knowledge, scales
from .models import AdverseEvent, DiaryEntry, DoseLog, Message, Patient, Prescription, ScaleAssignment, ScaleResult, User, now


class ScaleIn(BaseModel):
    scale_code: str = Field(max_length=32)
    answers: dict[str, float]
    client_id: str | None = Field(None, max_length=64)
    taken_at: datetime | None = None  # время заполнения на устройстве (офлайн)


class DiaryIn(BaseModel):
    day: date
    mood: int | None = Field(None, ge=0, le=10)
    anxiety: int | None = Field(None, ge=0, le=10)
    sleep_hours: float | None = Field(None, ge=0, le=24)
    sleep_quality: int | None = Field(None, ge=0, le=10)
    note: str | None = Field(None, max_length=4000)
    client_id: str | None = Field(None, max_length=64)


class DoseIn(BaseModel):
    dose_id: int | None = None          # отметка запланированного приёма
    prescription_id: int | None = None  # или внеплановая запись
    status: str = Field("taken", pattern="^(taken|skipped)$")
    taken_at: datetime | None = None
    client_id: str | None = Field(None, max_length=64)


class AdverseIn(BaseModel):
    title: str = Field(min_length=2, max_length=128)
    intensity: str = Field("mild", pattern="^(mild|moderate|severe)$")
    serious: bool = False
    life_threatening: bool = False
    description: str | None = Field(None, max_length=4000)
    client_id: str | None = Field(None, max_length=64)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    client_id: str | None = Field(None, max_length=64)


def ensure_can_submit(patient: Patient) -> None:
    if not patient.consent_at or patient.consent_withdrawn_at:
        raise HTTPException(403, "Нет действующего согласия на обработку персональных данных")
    if not patient.monitoring_active:
        raise HTTPException(409, "Дистанционное наблюдение не назначено врачом (требуется очный приём)")


def _existing(db: Session, model, patient_id: int, client_id: str | None):
    if not client_id:
        return None
    return db.scalar(select(model).where(model.patient_id == patient_id, model.client_id == client_id))


def submit_scale(db: Session, patient: Patient, data: ScaleIn, user: User, received_at: datetime) -> tuple[ScaleResult, list]:
    if user.role == "patient":
        ensure_can_submit(patient)
    if (dup := _existing(db, ScaleResult, patient.id, data.client_id)):
        return dup, []
    kb = knowledge.get(db)
    scale = kb["scale"].get(data.scale_code)
    if not scale:
        raise HTTPException(404, f"Шкала {data.scale_code} не найдена")
    if scale["respondent"] == "clinician" and user.role != "doctor":
        raise HTTPException(403, "Шкала заполняется врачом")
    try:
        res = scales.evaluate(scale, data.answers)
    except ValueError as e:
        raise HTTPException(422, str(e))
    taken_at = min(data.taken_at, received_at) if data.taken_at else received_at  # не из будущего
    r = ScaleResult(patient_id=patient.id, scale_code=data.scale_code, scale_version=kb["versions"].get(("scale", data.scale_code), 1),
                    answers=res["answers"], score=res["score"], band=res["band"], severity=res["severity"],
                    details={"subscales": res["subscales"], "critical_items": res["critical_items"]},
                    respondent=scale["respondent"], entered_by=user.id,
                    client_id=data.client_id, created_at=taken_at, received_at=received_at)
    db.add(r)
    # закрыть разовые назначения шкалы, сдвинуть периодические
    for a in db.scalars(select(ScaleAssignment).where(ScaleAssignment.patient_id == patient.id, ScaleAssignment.scale_code == data.scale_code,
                                                      ScaleAssignment.active.is_(True), ScaleAssignment.next_due <= date.today())):
        if a.every_days:
            a.next_due = date.today() + timedelta(days=a.every_days)
        else:
            a.active = False
    db.flush()
    return r, alerts.process(db, patient, f"scale:{r.id}", received_at)


def submit_diary(db: Session, patient: Patient, data: DiaryIn, received_at: datetime) -> tuple[DiaryEntry, list]:
    ensure_can_submit(patient)
    if (dup := _existing(db, DiaryEntry, patient.id, data.client_id)):
        return dup, []
    if data.day > received_at.date() + timedelta(days=1):
        raise HTTPException(422, "Дата записи в будущем")
    e = DiaryEntry(patient_id=patient.id, **data.model_dump(exclude={"note"}))
    db.add(e)
    e.note = data.note
    db.flush()
    return e, alerts.process(db, patient, f"diary:{e.id}", received_at)


def submit_dose(db: Session, patient: Patient, data: DoseIn, received_at: datetime) -> tuple[DoseLog, list]:
    ensure_can_submit(patient)
    if (dup := _existing(db, DoseLog, patient.id, data.client_id)):
        return dup, []
    t = min(data.taken_at, received_at) if data.taken_at else received_at
    if data.dose_id:
        d = db.get(DoseLog, data.dose_id)
        if not d or d.patient_id != patient.id:
            raise HTTPException(404, "Приём не найден")
        d.status, d.taken_at, d.client_id = data.status, t, data.client_id
    else:
        rx = db.get(Prescription, data.prescription_id) if data.prescription_id else None
        if not rx or rx.patient_id != patient.id:
            raise HTTPException(404, "Назначение не найдено")
        d = DoseLog(patient_id=patient.id, prescription_id=rx.id, scheduled_for=t, status=data.status, taken_at=t, client_id=data.client_id)
        db.add(d)
    db.flush()
    return d, alerts.process(db, patient, f"dose:{d.id}", received_at)


def submit_adverse(db: Session, patient: Patient, data: AdverseIn, received_at: datetime) -> tuple[AdverseEvent, list]:
    ensure_can_submit(patient)
    if (dup := _existing(db, AdverseEvent, patient.id, data.client_id)):
        return dup, []
    rx = db.scalar(select(Prescription).where(Prescription.patient_id == patient.id, Prescription.status == "active"))
    expected = None
    if rx:
        drug = knowledge.get(db)["drug"].get(rx.drug_id, {})
        known = [x.lower() for v in drug.get("adverse_reactions", {}).values() for x in v]
        title = data.title.lower()
        expected = any(k in title or title in k for k in known)
    e = AdverseEvent(patient_id=patient.id, prescription_id=rx.id if rx else None, expected=expected,
                     **data.model_dump(exclude={"description"}))
    if data.life_threatening:
        e.serious = True
    db.add(e)
    e.description = data.description
    db.flush()
    return e, alerts.process(db, patient, f"ae:{e.id}", received_at)


def send_message(db: Session, patient: Patient, user: User, data: MessageIn, received_at: datetime) -> tuple[Message, list]:
    if user.role == "patient":
        ensure_can_submit(patient)
    if (dup := _existing(db, Message, patient.id, data.client_id)):
        return dup, []
    m = Message(patient_id=patient.id, sender_id=user.id, sender_role=user.role, client_id=data.client_id)
    db.add(m)
    m.text = data.text
    db.flush()
    new_alerts = alerts.process(db, patient, f"msg:{m.id}", received_at) if user.role == "patient" else []
    # В канал уходит только факт сообщения; текст клиент запрашивает по API.
    # Push/SMS не раскрывают содержание (Закон 3185-1, ст. 9).
    ev = {"id": m.id, "patient_id": patient.id, "sender_role": m.sender_role}
    alerts.emit(db, patient_channel(patient.id), "message", ev)
    alerts.emit(db, doctor_channel(patient.doctor_id), "message", ev)
    return m, new_alerts


def message_dict(m: Message) -> dict:
    return {"id": m.id, "patient_id": m.patient_id, "sender_role": m.sender_role, "text": m.text,
            "created_at": m.created_at, "read_at": m.read_at}


def schedule_doses(db: Session, rx: Prescription, days: int = 42) -> None:
    """Плановые приёмы на курс — по ним считается приверженность."""
    times = {1: [9], 2: [8, 20], 3: [8, 14, 20]}.get(int(rx.regimen.get("times_per_day", 1)), [9])
    start = rx.started_at.date()
    for d in range(days):
        for h in times:
            t = datetime.combine(start + timedelta(days=d), datetime.min.time()) + timedelta(hours=h - 3)  # МСК -> UTC
            if t >= rx.started_at:
                db.add(DoseLog(patient_id=rx.patient_id, prescription_id=rx.id, scheduled_for=t, status="pending"))


def add_business_days(d: datetime, n: int) -> datetime:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d
