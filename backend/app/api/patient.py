from __future__ import annotations

import asyncio
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import auth, consent, services
from ..bus import bus, patient_channel
from ..db import defer_write, get_db
from ..engine import alerts, knowledge
from ..models import (AdverseEvent, Alert, DiaryEntry, DoseLog, Message, Prescription, ScaleAssignment, ScaleResult,
                      TrustedContact, User, now)

router = APIRouter(prefix="/api", tags=["patient"])
patient_only = auth.require("patient")


@router.get("/about")
def about():
    return consent.ABOUT


@router.get("/consent")
def consent_text():
    return {"version": consent.VERSION, "sha256": consent.SHA256, "text": consent.TEXT}


@router.get("/scales/{code}")
def scale_def(code: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    s = knowledge.get(db)["scale"].get(code)
    if not s:
        raise HTTPException(404, "Шкала не найдена")
    if user.role == "patient" and s["respondent"] != "patient":
        raise HTTPException(403, "Шкала заполняется врачом")
    return s


@router.get("/consent/trusted-contact")
def trusted_consent_text():
    return {"version": consent.TRUSTED_VERSION, "sha256": consent.TRUSTED_SHA256, "text": consent.TRUSTED_TEXT}


class TrustedIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    phone: str = Field(pattern=r"^\+?[0-9 ()-]{10,20}$")
    relation: str | None = Field(None, max_length=32)
    consent_version: str
    consent_sha256: str = Field(min_length=64, max_length=64)


def trusted_dict(t: TrustedContact) -> dict:
    return {"id": t.id, "name": t.name, "phone": t.phone, "relation": t.relation, "consent_at": t.consent_at}


@router.get("/me/trusted-contacts")
def my_trusted(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = auth.own_patient(user, db)
    return [trusted_dict(t) for t in db.scalars(select(TrustedContact).where(TrustedContact.patient_id == p.id, TrustedContact.revoked_at.is_(None)))]


@router.post("/me/trusted-contacts")
def add_trusted(data: TrustedIn, request: Request, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    """Доверенное лицо — только с отдельного согласия пациента на информирование."""
    if data.consent_version != consent.TRUSTED_VERSION or data.consent_sha256 != consent.TRUSTED_SHA256:
        raise HTTPException(409, "Текст согласия изменился — обновите страницу")
    p = auth.own_patient(user, db)
    t = TrustedContact(patient_id=p.id, relation=data.relation, consent_version=consent.TRUSTED_VERSION,
                       consent_text_sha256=consent.TRUSTED_SHA256)
    db.add(t)
    t.name, t.phone = data.name.strip(), data.phone.strip()
    auth.audit(db, user, "trusted_contact_consent_given", "trusted_contact", None, patient_id=p.id, ip=auth.client_ip(request),
               version=consent.TRUSTED_VERSION)
    db.commit()
    return trusted_dict(t)


@router.delete("/me/trusted-contacts/{tid}")
def revoke_trusted(tid: int, request: Request, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = auth.own_patient(user, db)
    t = db.get(TrustedContact, tid)
    if not t or t.patient_id != p.id:
        raise HTTPException(404, "Не найдено")
    t.revoked_at = now()
    auth.audit(db, user, "trusted_contact_consent_revoked", "trusted_contact", t.id, patient_id=p.id, ip=auth.client_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/me/overview")
def overview(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = auth.own_patient(user, db)
    doctor = db.get(User, p.doctor_id)
    rx = db.scalar(select(Prescription).where(Prescription.patient_id == p.id, Prescription.status == "active"))
    kb = knowledge.get(db)
    today = date.today()
    t0 = now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3)  # начало суток МСК в UTC
    doses = db.scalars(select(DoseLog).where(DoseLog.patient_id == p.id, DoseLog.scheduled_for >= t0,
                                            DoseLog.scheduled_for < t0 + timedelta(days=1)).order_by(DoseLog.scheduled_for)).all()
    due = db.scalars(select(ScaleAssignment).where(ScaleAssignment.patient_id == p.id, ScaleAssignment.active.is_(True),
                                                   ScaleAssignment.next_due <= today)).all()
    crisis = db.scalar(select(Alert).where(Alert.patient_id == p.id, Alert.severity == "critical", Alert.status != "resolved",
                                           Alert.created_at >= now() - timedelta(hours=24)).order_by(Alert.created_at.desc()))
    diary_today = db.scalar(select(DiaryEntry.id).where(DiaryEntry.patient_id == p.id, DiaryEntry.day == today))
    unread = len(db.scalars(select(Message.id).where(Message.patient_id == p.id, Message.sender_role == "doctor", Message.read_at.is_(None))).all())
    drug = kb["drug"].get(rx.drug_id) if rx else None
    return {
        "patient": {"id": p.id, "full_name": p.full_name, "code": p.code},
        "doctor": {"full_name": doctor.full_name, "specialty": doctor.specialty},
        "consent": {"accepted": bool(p.consent_at and not p.consent_withdrawn_at), "version": p.consent_version,
                    "current_version": consent.VERSION},
        "monitoring_active": p.monitoring_active,
        "therapy": rx and {"id": rx.id, "trade_name": drug["trade_name"] if drug else rx.drug_id, "regimen": rx.regimen,
                           "additional_monitoring": bool(drug and drug.get("additional_monitoring")),
                           "special_instructions": (drug or {}).get("special_instructions", [])},
        "doses_today": [{"id": d.id, "scheduled_for": d.scheduled_for, "status": d.status} for d in doses],
        "due_scales": [{"code": a.scale_code, "title": kb["scale"].get(a.scale_code, {}).get("title", a.scale_code), "reason": a.reason} for a in due],
        "diary_done_today": diary_today is not None,
        "crisis": crisis is not None and any(
            (x if isinstance(x, str) else next(iter(x))) == "crisis_screen" for x in crisis.actions),
        "crisis_contacts": consent.CRISIS_CONTACTS + [
            {"title": f"Доверенное лицо: {t.name}", "phone": t.phone}
            for t in db.scalars(select(TrustedContact).where(TrustedContact.patient_id == p.id, TrustedContact.revoked_at.is_(None)))],
        "unread_messages": unread,
    }


class ConsentIn(BaseModel):
    version: str
    sha256: str = Field(min_length=64, max_length=64)


@router.post("/me/consent")
def accept_consent(data: ConsentIn, request: Request, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    if data.version != consent.VERSION or data.sha256 != consent.SHA256:
        raise HTTPException(409, "Текст согласия изменился — обновите страницу")
    p = auth.own_patient(user, db)
    p.consent_version, p.consent_text_sha256, p.consent_at = consent.VERSION, consent.SHA256, now()
    p.consent_withdrawn_at = p.erase_after = None
    auth.audit(db, user, "consent_given", "patient", p.id, patient_id=p.id, version=consent.VERSION,
               sha256=consent.SHA256, ip=auth.client_ip(request))
    db.commit()
    return {"ok": True}


@router.post("/me/consent/withdraw")
def withdraw_consent(request: Request, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = auth.own_patient(user, db)
    p.consent_withdrawn_at = now()
    p.erase_after = now() + timedelta(days=30)  # 152-ФЗ ст. 21 ч. 5
    p.monitoring_active = False
    auth.audit(db, user, "consent_withdrawn", "patient", p.id, patient_id=p.id, ip=auth.client_ip(request))
    db.commit()
    return {"ok": True, "erase_after": p.erase_after}


def _received(request: Request):
    return request.state.received_at


@router.post("/me/scales")
def submit_scale(data: services.ScaleIn, request: Request, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = auth.own_patient(user, db)
    r, new = services.submit_scale(db, p, data, user, _received(request))
    alerts.commit(db)
    return {"id": r.id, "score": r.score, "band": r.band, "alerts": len(new), "crisis": _crisis(new)}


@router.post("/me/diary")
def submit_diary(data: services.DiaryIn, request: Request, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = auth.own_patient(user, db)
    e, new = services.submit_diary(db, p, data, _received(request))
    alerts.commit(db)
    return {"id": e.id, "alerts": len(new), "crisis": _crisis(new)}


@router.post("/me/doses")
def submit_dose(data: services.DoseIn, request: Request, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = auth.own_patient(user, db)
    d, _ = services.submit_dose(db, p, data, _received(request))
    alerts.commit(db)
    return {"id": d.id, "status": d.status}


@router.post("/me/adverse-events")
def submit_ae(data: services.AdverseIn, request: Request, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = auth.own_patient(user, db)
    e, new = services.submit_adverse(db, p, data, _received(request))
    alerts.commit(db)
    # Пациенту — только совет при тревожных признаках, без классификации реакции
    urgent = [f for f in (e.analysis or {}).get("red_flags", []) if f.get("level") == "critical"]
    return {"id": e.id, "alerts": len(new), "urgent": bool(urgent), "crisis": _crisis(new)}


@router.get("/me/messages")
def my_messages(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = auth.own_patient(user, db)
    msgs = db.scalars(select(Message).where(Message.patient_id == p.id).order_by(Message.created_at)).all()
    unread = [m.id for m in msgs if m.sender_role != "patient" and m.read_at is None]
    if unread:
        t = now()
        defer_write(db, lambda w: w.execute(update(Message).where(Message.id.in_(unread)).values(read_at=t)))
    return [services.message_dict(m) for m in msgs]


@router.post("/me/messages")
def post_message(data: services.MessageIn, request: Request, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = auth.own_patient(user, db)
    m, new = services.send_message(db, p, user, data, _received(request))
    alerts.commit(db)
    return {"id": m.id, "crisis": _crisis(new)}


class SyncItem(BaseModel):
    kind: str = Field(pattern="^(scale|diary|dose|adverse|message)$")
    data: dict


class SyncIn(BaseModel):
    items: list[SyncItem] = Field(max_length=500)


@router.post("/me/sync")
def sync(data: SyncIn, request: Request, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    """Пакетная выгрузка офлайн-очереди PWA. Каждый элемент обрабатывается
    независимо и идемпотентно: повтор после обрыва связи не создаёт дублей."""
    p = auth.own_patient(user, db)
    results = []
    for it in data.items:
        try:
            with db.begin_nested():
                if it.kind == "scale":
                    obj, _ = services.submit_scale(db, p, services.ScaleIn(**it.data), user, _received(request))
                elif it.kind == "diary":
                    obj, _ = services.submit_diary(db, p, services.DiaryIn(**it.data), _received(request))
                elif it.kind == "dose":
                    obj, _ = services.submit_dose(db, p, services.DoseIn(**it.data), _received(request))
                elif it.kind == "adverse":
                    obj, _ = services.submit_adverse(db, p, services.AdverseIn(**it.data), _received(request))
                else:
                    obj, _ = services.send_message(db, p, user, services.MessageIn(**it.data), _received(request))
            results.append({"client_id": it.data.get("client_id"), "ok": True, "id": obj.id})
        except HTTPException as e:
            results.append({"client_id": it.data.get("client_id"), "ok": False, "error": e.detail,
                            "retry": e.status_code >= 500})
        except ValueError as e:
            results.append({"client_id": it.data.get("client_id"), "ok": False, "error": str(e), "retry": False})
    alerts.commit(db)
    return {"results": results}


@router.get("/me/history")
def history(days: int = 90, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    p = auth.own_patient(user, db)
    return history_for(db, p.id, days)


def history_for(db: Session, patient_id: int, days: int) -> dict:
    since = now() - timedelta(days=min(days, 3650))
    scales: dict[str, list] = {}
    for r in db.scalars(select(ScaleResult).where(ScaleResult.patient_id == patient_id, ScaleResult.created_at >= since).order_by(ScaleResult.created_at)):
        scales.setdefault(r.scale_code, []).append({"at": r.created_at, "score": r.score, "band": r.band, "severity": r.severity})
    diary = [{"day": d.day, "mood": d.mood, "anxiety": d.anxiety, "sleep_hours": d.sleep_hours, "sleep_quality": d.sleep_quality}
             for d in db.scalars(select(DiaryEntry).where(DiaryEntry.patient_id == patient_id, DiaryEntry.day >= since.date()).order_by(DiaryEntry.day))]
    by_day: dict[str, list[int]] = {}
    for d in db.scalars(select(DoseLog).where(DoseLog.patient_id == patient_id, DoseLog.scheduled_for >= since, DoseLog.scheduled_for <= now())):
        k = (d.scheduled_for + timedelta(hours=3)).date().isoformat()
        by_day.setdefault(k, [0, 0])
        by_day[k][1] += 1
        by_day[k][0] += d.status == "taken"
    adherence = [{"day": k, "taken": v[0], "planned": v[1]} for k, v in sorted(by_day.items())]
    return {"scales": scales, "diary": diary, "adherence": adherence}


@router.get("/me/doses.ics")
def dose_reminders(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    """Напоминания о приёме препарата для календаря телефона (формат iCalendar)."""
    p = auth.own_patient(user, db)
    ics = services.dose_calendar(db, p)
    if ics is None:
        raise HTTPException(404, "Нет действующего назначения с запланированными приёмами")
    return Response(ics, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="kompas-reminders.ics"'})


@router.get("/me/export")
def export(request: Request, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    """Право субъекта на доступ к своим данным (152-ФЗ ст. 14)."""
    p = auth.own_patient(user, db)
    auth.audit(db, user, "self_export", "patient", p.id, patient_id=p.id, ip=auth.client_ip(request))
    db.commit()
    return {
        "patient": {"full_name": p.full_name, "birth_date": p.birth_date, "sex": p.sex, "diagnoses": p.diagnoses,
                    "consent_at": p.consent_at, "consent_version": p.consent_version},
        "history": history_for(db, p.id, 3650),
        "diary_notes": [{"day": d.day, "note": d.note} for d in db.scalars(select(DiaryEntry).where(DiaryEntry.patient_id == p.id)) if d.note_enc],
        "adverse_events": [{"at": a.created_at, "title": a.title, "intensity": a.intensity, "description": a.description}
                           for a in db.scalars(select(AdverseEvent).where(AdverseEvent.patient_id == p.id))],
        "messages": [services.message_dict(m) for m in db.scalars(select(Message).where(Message.patient_id == p.id))],
    }


@router.get("/me/stream")
async def stream(ticket: str, request: Request, last_event_id: int | None = None, db: Session = Depends(get_db)):
    def _redeem_in_worker(value: str):
        from ..db import SessionLocal
        with SessionLocal() as ticket_db:
            return auth.redeem_ticket(value, ticket_db)
    user = await asyncio.to_thread(_redeem_in_worker, ticket)
    if user.role != "patient":
        raise HTTPException(403, "Недостаточно прав")
    p = auth.own_patient(user, db)
    db.close()
    return sse(patient_channel(p.id), _last_id(request, last_event_id))


def _last_id(request: Request, q: int | None) -> int | None:
    h = request.headers.get("last-event-id")
    return q if q is not None else (int(h) if h and h.isdigit() else None)


def sse(channel: str, last_event_id: int | None = None) -> StreamingResponse:
    """SSE-поток. При переподключении (Last-Event-ID) пропущенные события досылаются."""
    async def gen():
        q = bus.subscribe(channel)
        try:
            yield "retry: 2000\nevent: ready\ndata: {}\n\n"
            if last_event_id is not None:
                for item in await asyncio.to_thread(bus.replay, channel, last_event_id):
                    yield item
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keep-alive через прокси
        finally:
            bus.unsubscribe(channel, q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _crisis(alerts) -> bool:
    return any((x if isinstance(x, str) else next(iter(x))) == "crisis_screen" for a in alerts for x in a.actions)
