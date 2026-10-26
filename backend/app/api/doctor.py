from __future__ import annotations

import asyncio

import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import auth, services
from ..bus import doctor_channel, patient_channel
from ..crypto import vault
from ..db import defer_write, get_db
from ..engine import alerts, context, extract, fhir, knowledge, logic, recommend
from ..models import (AdverseEvent, Alert, ClinicalAction, Document, Message, Patient, Prescription, ScaleAssignment,
                      ScaleResult, TrustedContact, User, Visit, now)
from .patient import _last_id, history_for, sse

router = APIRouter(prefix="/api/doctor", tags=["doctor"])
doctor_only = auth.require("doctor")


def _p(user: User, patient_id: int, db: Session, request: Request | None = None, action: str = "view") -> Patient:
    p = auth.patient_for(user, patient_id, db)
    auth.audit(db, user, f"patient_{action}", "patient", p.id, patient_id=p.id, ip=auth.client_ip(request))
    return p


# --- список пациентов (автотриаж) --------------------------------------------
@router.get("/patients")
def list_patients(response: Response,
                  q: str | None = Query(None, max_length=128, description="Код пациента или часть ФИО"),
                  only_alerts: bool = False,
                  severity: str | None = Query(None, pattern="^(critical|high|medium)$", description="Есть открытый алерт не ниже уровня"),
                  icd: str | None = Query(None, max_length=8, description="Диагноз МКБ-10 (префикс), напр. F41"),
                  drug: str | None = Query(None, max_length=64, description="Текущая терапия, id препарата"),
                  referral: str | None = Query(None, pattern="^(mandatory|desirable)$"),
                  adherence_below: int | None = Query(None, ge=0, le=100),
                  scale: str | None = Query(None, max_length=16), min_score: int | None = None,
                  monitoring: bool | None = None,
                  needs_attention: bool = False,
                  sort: str = Query("risk", pattern="^(risk|name|age|last_diary)$"), desc: bool = True,
                  limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                  user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """Список своих пациентов: автотриаж по риску, поиск и фильтры. ФИО хранится
    зашифрованным, поэтому поиск по части ФИО выполняется по расшифрованным данным
    только своих пациентов (в памяти, не в БД)."""
    stmt = select(Patient).where(Patient.doctor_id == user.id, Patient.erased_at.is_(None))
    if monitoring is not None:
        stmt = stmt.where(Patient.monitoring_active.is_(monitoring))
    patients = db.scalars(stmt.order_by(Patient.risk_score.desc())).all()
    if q:
        needle = q.strip().lower().replace("ё", "е")
        patients = [p for p in patients if p.code.lower() == needle or needle in (p.full_name or "").lower().replace("ё", "е")]
    if icd:
        patients = [p for p in patients if any(isinstance(d, dict) and isinstance(d.get("icd10"), str) and d["icd10"].startswith(icd.upper()) for d in (p.diagnoses or []))]
    ids = [p.id for p in patients]
    open_alerts: dict[int, dict] = {}
    for a in db.scalars(select(Alert).where(Alert.patient_id.in_(ids), Alert.status != "resolved")):
        d = open_alerts.setdefault(a.patient_id, {"critical": 0, "high": 0, "medium": 0})
        d[a.severity] = d.get(a.severity, 0) + 1
    referral_levels: dict[int, set[str]] = {}
    for action in db.scalars(select(ClinicalAction).where(
        ClinicalAction.patient_id.in_(ids), ClinicalAction.kind == "referral",
        ClinicalAction.status.in_(["proposed", "confirmed"]))):
        if action.level:
            referral_levels.setdefault(action.patient_id, set()).add(action.level)
    referrals = {
        pid: ("mandatory" if "mandatory" in levels else "desirable" if "desirable" in levels else sorted(levels)[0])
        for pid, levels in referral_levels.items() if levels
    }
    pending = dict(db.execute(select(ClinicalAction.patient_id, func.count()).where(
        ClinicalAction.patient_id.in_(ids), ClinicalAction.status == "proposed").group_by(ClinicalAction.patient_id)).all())
    out = []
    kb = knowledge.get(db)
    rank = {"medium": 1, "high": 2, "critical": 3}
    for p in patients:
        if only_alerts and p.id not in open_alerts:
            continue
        if severity and not any(rank[s] >= rank[severity] and n for s, n in open_alerts.get(p.id, {}).items()):
            continue
        if referral and referrals.get(p.id) != referral:
            continue
        if needs_attention and not (
            any(open_alerts.get(p.id, {}).get(level, 0) for level in ("critical", "high"))
            or referrals.get(p.id) == "mandatory"
            or pending.get(p.id, 0) > 0
        ):
            continue
        ctx = context.build(db, p)
        rx = db.scalar(select(Prescription).where(Prescription.patient_id == p.id, Prescription.status == "active"))
        out.append({
            "id": p.id, "code": p.code, "full_name": p.full_name, "age": ctx["patient"]["age"], "sex": p.sex,
            "diagnoses": p.diagnoses, "risk_score": p.risk_score, "monitoring_active": p.monitoring_active,
            "therapy": rx and kb["drug"].get(rx.drug_id, {}).get("trade_name", rx.drug_id),
            "scales": {k: {"score": v["score"], "band": v["band"], "severity": v["severity"], "delta": v["delta"]}
                       for k, v in ctx["scales"].items()},
            "adherence_pct": ctx["adherence"]["pct_14d"],
            "alerts": open_alerts.get(p.id, {}), "referral": referrals.get(p.id), "pending_actions": pending.get(p.id, 0),
            "last_diary_days": ctx["diary"]["days_since_last"],
            "_drug_id": rx.drug_id if rx else None,
        })
    if drug:
        out = [x for x in out if x["_drug_id"] == drug]
    if adherence_below is not None:
        out = [x for x in out if x["adherence_pct"] is not None and x["adherence_pct"] < adherence_below]
    if scale:
        out = [x for x in out if scale in x["scales"] and (min_score is None or x["scales"][scale]["score"] >= min_score)]
    keys = {"risk": lambda x: x["risk_score"], "name": lambda x: x["full_name"] or "", "age": lambda x: x["age"] or 0,
            "last_diary": lambda x: x["last_diary_days"] if x["last_diary_days"] is not None else 10**6}
    out.sort(key=keys[sort], reverse=desc)
    for x in out:
        x.pop("_drug_id")
    response.headers["X-Total-Count"] = str(len(out))
    db.commit()
    return out[offset:offset + limit]


# --- создание пациента -----------------------------------------------------
def _validated_diagnoses(items: list[dict] | None) -> list[dict] | None:
    """Validate diagnosis JSON before it reaches clinical logic or analytics.

    The database stores diagnoses as JSON for backwards compatibility, so validate
    the shape at the API boundary and keep a defensive fallback for legacy rows.
    """
    if items is None:
        return None
    if len(items) > 30:
        raise ValueError("Допускается не более 30 диагнозов")
    result: list[dict] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Диагноз {i + 1}: ожидается объект")
        code = item.get("icd10")
        if not isinstance(code, str):
            raise ValueError(f"Диагноз {i + 1}: укажите код МКБ-10")
        code = code.strip().upper()
        # Basic ICD-10 code shape (e.g. F41.1, F32.1, I10); correctness of the
        # clinical coding still belongs to the treating clinician.
        if not re.fullmatch(r"[A-Z][0-9A-Z]{2}(?:\.[0-9A-Z]{1,4})?", code):
            raise ValueError(f"Диагноз {i + 1}: некорректный формат кода МКБ-10")
        title = item.get("title")
        if title is not None and (not isinstance(title, str) or len(title) > 256):
            raise ValueError(f"Диагноз {i + 1}: название должно быть строкой до 256 символов")
        primary = item.get("primary", False)
        if not isinstance(primary, bool):
            raise ValueError(f"Диагноз {i + 1}: поле primary должно быть логическим")
        result.append({**item, "icd10": code, "title": title, "primary": primary})
    if sum(1 for d in result if d.get("primary")) > 1:
        raise ValueError("Основным может быть отмечен только один диагноз")
    return result


class PatientIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=128)
    birth_date: date
    sex: str = Field(pattern="^(m|f)$")
    phone: str | None = Field(None, max_length=32)
    emergency_contact: str | None = Field(None, max_length=128)
    profile: dict = Field(default_factory=dict)
    diagnoses: list[dict] = Field(default_factory=list)
    current_meds: list[dict] = Field(default_factory=list)
    therapy_history: list[dict] = Field(default_factory=list)
    maoi_stopped_at: date | None = None
    in_person_visit: bool = True  # пациент заводится на очном приёме

    @field_validator("diagnoses")
    @classmethod
    def validate_diagnoses(cls, value: list[dict]) -> list[dict]:
        return _validated_diagnoses(value) or []


def _code(db: Session) -> str:
    while True:
        c = "P-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        if not db.scalar(select(Patient.id).where(Patient.code == c)):
            return c


def _normalize_meds(db: Session, meds: list[dict]) -> list[dict]:
    kb = knowledge.get(db)
    out = []
    for m in meds:
        inn, classes = knowledge.classes_for(kb, m.get("inn") or m.get("name", ""))
        out.append({**m, "inn": inn or m.get("inn"), "classes": m.get("classes") or classes})
    return out


OUTCOMES = {"response", "partial", "no_response", "intolerance", "unknown"}


def _validate_history(items: list[dict]) -> list[dict]:
    out = []
    for c in items:
        if not isinstance(c, dict) or not c.get("inn") or c.get("outcome", "unknown") not in OUTCOMES:
            raise HTTPException(422, f"Курс терапии: нужны inn и outcome из {sorted(OUTCOMES)}")
        out.append({"inn": str(c["inn"]).lower(), "dose": c.get("dose"), "weeks": c.get("weeks"), "outcome": c.get("outcome", "unknown")})
    return out


@router.post("/patients")
def create_patient(data: PatientIn, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    login = "p" + secrets.token_hex(3)
    password = secrets.token_urlsafe(9)  # выдаётся пациенту один раз, смена при первом входе
    pu = User(login=login, password_hash=auth.hash_password(password), role="patient", full_name="Пациент", must_change_password=True)
    db.add(pu)
    db.flush()
    p = Patient(code=_code(db), user_id=pu.id, doctor_id=user.id, sex=data.sex, profile=data.profile,
                diagnoses=data.diagnoses, current_meds=_normalize_meds(db, data.current_meds),
                therapy_history=_validate_history(data.therapy_history), maoi_stopped_at=data.maoi_stopped_at)
    db.add(p)
    db.flush()
    p.full_name = data.full_name.strip()
    p.birth_date = data.birth_date
    p.contacts = json.dumps({"phone": data.phone, "emergency_contact": data.emergency_contact}, ensure_ascii=False)
    p.name_bidx = vault.blind_index(data.full_name)
    if data.in_person_visit:
        p.in_person_visit_at, p.diagnosis_confirmed_by = now(), user.id
    auth.audit(db, user, "patient_created", "patient", p.id, patient_id=p.id, ip=auth.client_ip(request))
    alerts.process(db, p, f"created:{p.id}")
    alerts.commit(db)
    return {"id": p.id, "code": p.code, "login": login, "temporary_password": password}



@router.post("/patients/{pid}/reset-patient-password")
def reset_patient_password(pid: int, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """Лечащий врач может выдать пациенту новый временный пароль; администратор — нет."""
    patient = _p(user, pid, db, request, "password_reset")
    if not patient.user_id:
        raise HTTPException(409, "У пациента нет связанной учётной записи")
    patient_user = db.get(User, patient.user_id)
    if not patient_user or patient_user.role != "patient" or not patient_user.active:
        raise HTTPException(409, "Учётная запись пациента недоступна")
    password = secrets.token_urlsafe(12)
    patient_user.password_hash = auth.hash_password(password)
    patient_user.password_changed_at = now()
    patient_user.must_change_password = True
    patient_user.failed_logins = 0
    patient_user.locked_until = None
    auth.revoke_all(db, patient_user.id)
    auth.audit(db, user, "patient_password_reset", "patient", patient.id, patient_id=patient.id,
               ip=auth.client_ip(request), account_id=patient_user.id)
    db.commit()
    return {"temporary_password": password}


# --- карточка ----------------------------------------------------------------
@router.get("/patients/{pid}")
def card(pid: int, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request)
    kb = knowledge.get(db)
    ctx = context.build(db, p)
    rxs = db.scalars(select(Prescription).where(Prescription.patient_id == p.id).order_by(Prescription.started_at.desc())).all()
    prof = p.profile or {}
    bmi = None
    if prof.get("height_cm") and prof.get("weight_kg"):
        bmi = round(prof["weight_kg"] / (prof["height_cm"] / 100) ** 2, 1)
    active_rx = next((r for r in rxs if r.status == "active"), None)
    res = {
        # шапка карточки (по запросу врачей): ФИО, возраст, ИМТ, препараты, диагноз, аллергии
        "header": {
            "full_name": p.full_name, "age": ctx["patient"]["age"], "sex": p.sex,
            "bmi": bmi, "height_cm": prof.get("height_cm"), "weight_kg": prof.get("weight_kg"),
            "diagnoses": p.diagnoses,
            "medications": ([{"name": kb["drug"].get(active_rx.drug_id, {}).get("trade_name", active_rx.drug_id),
                              "regimen": active_rx.regimen, "prescribed_here": True}] if active_rx else [])
                           + [{"name": m.get("name") or m.get("inn"), "dose": m.get("dose"), "prescribed_here": False} for m in p.current_meds],
            "allergies": prof.get("allergies", []),
        },
        "trusted_contacts": [{"name": t.name, "phone": t.phone, "relation": t.relation, "consent_at": t.consent_at}
                             for t in db.scalars(select(TrustedContact).where(TrustedContact.patient_id == p.id, TrustedContact.revoked_at.is_(None)))],
        "patient": {
            "id": p.id, "code": p.code, "full_name": p.full_name, "birth_date": p.birth_date, "age": ctx["patient"]["age"],
            "sex": p.sex, "contacts": json.loads(p.contacts or "{}"), "profile": p.profile, "diagnoses": p.diagnoses,
            "current_meds": p.current_meds, "therapy_history": p.therapy_history, "maoi_stopped_at": p.maoi_stopped_at,
            "in_person_visit_at": p.in_person_visit_at, "monitoring_active": p.monitoring_active,
            "consent": {"at": p.consent_at, "version": p.consent_version, "withdrawn_at": p.consent_withdrawn_at},
            "thresholds": ctx["thresholds"], "threshold_overrides": p.alert_thresholds,
        },
        "context": {k: ctx[k] for k in ("scales", "diary", "adherence", "therapy", "ae", "flags")},
        "prescriptions": [{
            "id": r.id, "drug_id": r.drug_id, "trade_name": kb["drug"].get(r.drug_id, {}).get("trade_name", r.drug_id),
            "indication_id": r.indication_id, "regimen": r.regimen, "status": r.status, "off_label": r.off_label,
            "mode": r.mode, "rationale": r.rationale, "started_at": r.started_at, "stopped_at": r.stopped_at,
            "additional_monitoring": kb["drug"].get(r.drug_id, {}).get("additional_monitoring", False),
        } for r in rxs],
        "alerts": [alerts.alert_dict(a, p) for a in db.scalars(select(Alert).where(Alert.patient_id == p.id).order_by(Alert.created_at.desc()).limit(50))],
        "actions": [action_dict(a) for a in db.scalars(select(ClinicalAction).where(ClinicalAction.patient_id == p.id).order_by(ClinicalAction.created_at.desc()))],
        "adverse_events": [{"id": a.id, "title": a.title, "intensity": a.intensity, "serious": a.serious, "life_threatening": a.life_threatening,
                            "expected": a.expected, "description": a.description, "status": a.status, "created_at": a.created_at,
                            "analysis": a.analysis}
                           for a in db.scalars(select(AdverseEvent).where(AdverseEvent.patient_id == p.id).order_by(AdverseEvent.created_at.desc()))],
        "assignments": [{"id": a.id, "scale_code": a.scale_code, "every_days": a.every_days, "next_due": a.next_due, "reason": a.reason}
                        for a in db.scalars(select(ScaleAssignment).where(ScaleAssignment.patient_id == p.id, ScaleAssignment.active.is_(True)))],
        "documents": [{"id": d.id, "filename": d.filename, "extractor": d.extractor, "applied": d.applied, "created_at": d.created_at}
                      for d in db.scalars(select(Document).where(Document.patient_id == p.id).order_by(Document.created_at.desc()))],
        "history": history_for(db, p.id, 180),
        "visits": [visit_dict(v) for v in db.scalars(select(Visit).where(Visit.patient_id == p.id).order_by(Visit.at.desc()).limit(20))],
    }
    db.commit()
    return res


class PatientPatch(BaseModel):
    profile: dict | None = None
    diagnoses: list[dict] | None = None
    current_meds: list[dict] | None = None
    therapy_history: list[dict] | None = None
    maoi_stopped_at: date | None = None
    alert_thresholds: dict | None = None

    @field_validator("diagnoses")
    @classmethod
    def validate_diagnoses(cls, value: list[dict] | None) -> list[dict] | None:
        return _validated_diagnoses(value)


@router.patch("/patients/{pid}")
def patch_patient(pid: int, data: PatientPatch, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request, "update")
    changed = data.model_dump(exclude_unset=True)
    if "alert_thresholds" in changed:
        allowed = context.thresholds(knowledge.get(db), Patient(alert_thresholds={}))
        bad = [k for k, v in (data.alert_thresholds or {}).items() if k not in allowed or not isinstance(v, (int, float)) or v < 0]
        if bad:
            raise HTTPException(422, f"Недопустимые пороги: {bad}")
    if "current_meds" in changed:
        changed["current_meds"] = _normalize_meds(db, data.current_meds or [])
    if "therapy_history" in changed:
        changed["therapy_history"] = _validate_history(data.therapy_history or [])
    for k, v in changed.items():
        setattr(p, k, v)
    auth.audit(db, user, "patient_fields_changed", "patient", p.id, patient_id=p.id, fields=sorted(changed))
    alerts.process(db, p, f"patch:{now().isoformat()}")
    alerts.commit(db)
    return {"ok": True}


class VisitIn(BaseModel):
    kind: str = Field("in_person", pattern="^(in_person|telemedicine|async)$")
    reason: str | None = Field(None, max_length=256)
    notes: str | None = Field(None, max_length=20000)
    plan: dict = Field(default_factory=dict)
    next_visit_at: datetime | None = None
    diagnosis_confirmed: bool = True

    @field_validator("next_visit_at")
    @classmethod
    def normalize_next_visit_at(cls, value: datetime | None) -> datetime | None:
        # Store UTC-naive timestamps consistently with the existing model/database contract.
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


def visit_dict(v: Visit) -> dict:
    return {"id": v.id, "kind": v.kind, "at": v.at, "doctor_id": v.doctor_id, "reason": v.reason, "notes": v.notes,
            "plan": v.plan, "next_visit_at": v.next_visit_at}


@router.post("/patients/{pid}/visits")
def add_visit(pid: int, data: VisitIn, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """Визит. Очный приём с установлением диагноза — основание для дистанционного
    наблюдения и дистанционной коррекции терапии (193н п. 38, 43)."""
    p = _p(user, pid, db, request, "visit")
    v = Visit(patient_id=p.id, doctor_id=user.id, kind=data.kind, at=now(), reason=data.reason, plan=data.plan,
              next_visit_at=data.next_visit_at)
    db.add(v)
    v.notes = data.notes
    if data.kind == "in_person" and data.diagnosis_confirmed:
        p.in_person_visit_at, p.diagnosis_confirmed_by = v.at, user.id
    db.commit()
    return visit_dict(v)


@router.post("/patients/{pid}/visit")
def register_visit(pid: int, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """Короткая форма: отметить очный приём."""
    return add_visit(pid, VisitIn(), request, user, db)


@router.get("/patients/{pid}/visits")
def list_visits(pid: int, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request, "visits")
    return [visit_dict(v) for v in db.scalars(select(Visit).where(Visit.patient_id == p.id).order_by(Visit.at.desc()))]


class MonitoringIn(BaseModel):
    active: bool


@router.post("/patients/{pid}/monitoring")
def set_monitoring(pid: int, data: MonitoringIn, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request, "monitoring")
    if data.active and not p.in_person_visit_at:
        raise HTTPException(409, "Дистанционное наблюдение назначается по результатам очного приёма (Приказ МЗ РФ № 193н, п. 43)")
    p.monitoring_active = data.active
    db.commit()
    return {"ok": True}


# --- рекомендации и назначения ---------------------------------------------
@router.get("/patients/{pid}/recommendations")
def recommendations(pid: int, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request, "recommendations")
    res = recommend.recommend(context.build(db, p), knowledge.get(db))
    db.commit()
    return res


MONITORING_PLAN = "План мониторинга:"


class RegimenIn(BaseModel):
    """Dose parameters entered by a clinician; daily dose is computed server-side."""
    dose_mg: float = Field(gt=0, le=1000)
    times_per_day: int = Field(ge=1, le=8)


class PrescribeIn(BaseModel):
    drug_id: str
    indication_id: str | None = None
    regimen: RegimenIn | None = None
    mode: str = Field("in_person", pattern="^(in_person|remote)$")
    rationale: str | None = Field(None, max_length=2000)
    acknowledge_off_label: bool = False
    acknowledge_contraindications: bool = False


@router.post("/patients/{pid}/prescriptions")
def prescribe(pid: int, data: PrescribeIn, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """Назначение подтверждается врачом; выбранное показание и режим повторно проверяются сервером."""
    p = _p(user, pid, db, request, "prescribe")
    kb = knowledge.get(db)
    drug = kb["drug"].get(data.drug_id)
    if not drug:
        raise HTTPException(404, "Препарат не найден в справочнике (рекомендуются только препараты, зарегистрированные в РФ)")
    warnings: list[str] = []
    if drug.get("verified") is not True:
        # Не блокируем: решение за врачом, но предупреждаем и фиксируем в аудите
        warnings.append("Сведения о препарате ещё не сверены с инструкцией в ГРЛС — проверьте режим и противопоказания по инструкции")
    if data.mode == "remote" and not p.in_person_visit_at:
        raise HTTPException(409, "Дистанционная коррекция терапии возможна только после установления диагноза на очном приёме (193н п. 38)")
    ctx = context.build(db, p)
    ev = recommend.evaluate_drug(drug, ctx, kb)
    if ev["status"] == "contraindicated" and not (data.acknowledge_contraindications and data.rationale and len(data.rationale.strip()) >= 20):
        raise HTTPException(409, {"message": "Противопоказано по инструкции. Для назначения требуется подтверждение и обоснование врача.", "evaluation": ev})
    if ev["status"] == "off_label" and not (data.acknowledge_off_label and data.rationale and len(data.rationale.strip()) >= 20):
        raise HTTPException(409, {"message": "Нет зарегистрированного показания. Применение вне инструкции — только с обоснованием врача.", "evaluation": ev})
    if ev["status"] == "off_label" and data.regimen is None:
        raise HTTPException(422, "Для внеинструкционного назначения врач должен явно указать дозу и частоту приёма")

    # Do not trust a caller-supplied indication_id: it must independently match
    # the patient's diagnosis and any structured conditions required by that indication.
    ind = None
    if data.indication_id:
        ind = next((item for item in drug.get("indications", []) if item.get("id") == data.indication_id), None)
        if ind is None:
            raise HTTPException(422, "Указанное показание отсутствует в инструкции препарата")
        matches_icd = any(code.startswith(prefix) for code in ctx["patient"].get("icd10", [])
                          for prefix in ind.get("icd10", []))
        needs_match = "requires" not in ind or logic.safe_eval(ind["requires"], ctx, f"drug:{drug['id']}:indication:{ind['id']}")
        if not matches_icd or not needs_match:
            raise HTTPException(422, "Выбранное показание не подтверждается данными пациента; укажите применимое показание или оформите внеинструкционное применение без indication_id")
    elif ev.get("indication"):
        ind = next((item for item in drug.get("indications", []) if item.get("id") == ev["indication"].get("id")), None)

    regimen = dict((ind or {}).get("regimen") or {"dose_mg": None, "times_per_day": 1})
    if data.regimen is not None:
        # Жёсткий предел — только максимальная суточная доза из инструкции (по показанию,
        # а вне показаний — наибольшая из зарегистрированных). Нет предела в справочнике —
        # предупреждение врачу, а не отказ: дозу выбирает врач.
        limits = [float(x["regimen"]["max_daily_mg"]) for x in ([ind] if ind else drug.get("indications", []))
                  if (x.get("regimen") or {}).get("max_daily_mg")]
        max_daily = max(limits) if limits else None
        daily = float(data.regimen.dose_mg) * int(data.regimen.times_per_day)
        if max_daily is not None and daily > max_daily + 1e-9:
            raise HTTPException(422, {"message": f"Суточная доза превышает максимальную по инструкции ({max_daily:g} мг/сут)", "max_daily_mg": max_daily})
        if max_daily is None:
            warnings.append("В справочнике не указана максимальная суточная доза — сверьте дозу с инструкцией")
        regimen.update({"dose_mg": float(data.regimen.dose_mg), "times_per_day": int(data.regimen.times_per_day),
                        "daily_mg": round(daily, 3), "max_daily_mg": max_daily})

    # A contradictory evaluator result indicates stale/malformed knowledge and must not
    # silently turn into a registered-indication prescription.
    if ind is not None and ev["status"] == "off_label":
        raise HTTPException(409, "Конфликт оценки показания и справочника. Обновите/проверьте справочник перед назначением.")

    for old in db.scalars(select(Prescription).where(Prescription.patient_id == p.id, Prescription.status.in_(["active", "paused"]))):
        old.status, old.stopped_at = "stopped", now()
    rx = Prescription(patient_id=p.id, drug_id=drug["id"], indication_id=ind and ind["id"], regimen=regimen,
                      off_label=ev["status"] != "indicated", mode=data.mode, confirmed_by=user.id)
    db.add(rx)
    rx.rationale = data.rationale
    db.flush()
    services.schedule_doses(db, rx)
    # План мониторинга прежнего препарата заменяется планом нового; шкалы, назначенные
    # врачом вручную, сохраняются и не дублируются
    for a in db.scalars(select(ScaleAssignment).where(ScaleAssignment.patient_id == p.id, ScaleAssignment.active.is_(True),
                                                      ScaleAssignment.reason.startswith(MONITORING_PLAN))):
        a.active = False
    manual = set(db.scalars(select(ScaleAssignment.scale_code).where(
        ScaleAssignment.patient_id == p.id, ScaleAssignment.active.is_(True), ScaleAssignment.every_days.is_not(None))))
    for scale in (drug.get("monitoring") or {}).get("scales", []):
        if scale["scale"] in manual:
            continue
        db.add(ScaleAssignment(patient_id=p.id, scale_code=scale["scale"], every_days=scale["every_days"], next_due=date.today(),
                               reason=f"{MONITORING_PLAN} {drug['trade_name']}"))
    auth.audit(db, user, "prescription_confirmed", "prescription", rx.id, patient_id=p.id, drug=drug["id"],
               status=ev["status"], mode=data.mode, indication=ind and ind["id"], regimen=regimen, warnings=warnings)
    alerts.process(db, p, f"rx:{rx.id}")
    alerts.commit(db)
    return {"id": rx.id, "status": ev["status"], "regimen": regimen, "warnings": warnings}


class StopIn(BaseModel):
    action: str = Field(pattern="^(stop|pause|resume)$")
    reason: str | None = Field(None, max_length=2000)


@router.post("/prescriptions/{rid}")
def change_prescription(rid: int, data: StopIn, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    rx = db.get(Prescription, rid)
    if not rx:
        raise HTTPException(404, "Назначение не найдено")
    p = _p(user, rx.patient_id, db, request, "prescription_change")
    if not p.in_person_visit_at:
        raise HTTPException(409, "Коррекция терапии возможна только после очного приёма (193н п. 38)")
    if data.action == "resume":
        kb = knowledge.get(db)
        drug = kb.get("drug", {}).get(rx.drug_id)
        if not drug:
            raise HTTPException(409, "Препарат больше отсутствует в действующем справочнике; создайте новое назначение после проверки врачом")
        ev = recommend.evaluate_drug(drug, context.build(db, p), kb)
        if ev["status"] == "contraindicated":
            raise HTTPException(409, {"message": "Возобновление заблокировано: текущая оценка выявила противопоказание или критическое взаимодействие. Проверьте карточку и оформите новое решение врача.", "evaluation": ev})
        other_active = db.scalar(select(Prescription.id).where(
            Prescription.patient_id == p.id, Prescription.status == "active", Prescription.id != rx.id).limit(1))
        if other_active:
            raise HTTPException(409, "У пациента уже есть другое действующее назначение; сначала согласуйте план терапии")
        if rx.indication_id:
            ind = next((item for item in drug.get("indications", []) if item.get("id") == rx.indication_id), None)
            if not ind:
                raise HTTPException(409, "Показание старого назначения отсутствует в справочнике; создайте новое назначение после проверки")
            ctx = context.build(db, p)
            matches_icd = any(code.startswith(prefix) for code in ctx["patient"].get("icd10", []) for prefix in ind.get("icd10", []))
            needs_match = "requires" not in ind or logic.safe_eval(ind["requires"], ctx, f"drug:{drug['id']}:indication:{ind['id']}")
            if not matches_icd or not needs_match:
                raise HTTPException(409, "Данные пациента больше не соответствуют показанию старого назначения; оформите новое решение врача")
        elif not (rx.off_label and data.reason and len(data.reason.strip()) >= 20):
            raise HTTPException(409, "Для возобновления внеинструкционного назначения требуется новое обоснование врача не короче 20 символов")
    rx.status = {"stop": "stopped", "pause": "paused", "resume": "active"}[data.action]
    if data.action == "stop":
        rx.stopped_at = now()
    auth.audit(db, user, f"prescription_{data.action}", "prescription", rx.id, patient_id=p.id)
    alerts.emit(db, patient_channel(p.id), "therapy_changed", {"prescription_id": rx.id})
    alerts.commit(db)
    return {"ok": True, "status": rx.status}


# --- шкалы врача, назначения шкал ------------------------------------------
@router.post("/patients/{pid}/scales")
def clinician_scale(pid: int, data: services.ScaleIn, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request, "scale_entry")
    r, new = services.submit_scale(db, p, data, user, request.state.received_at)
    alerts.commit(db)
    return {"id": r.id, "score": r.score, "band": r.band, "alerts": len(new)}


class AssignIn(BaseModel):
    scale_code: str
    every_days: int | None = Field(None, ge=1, le=365)
    reason: str | None = Field(None, max_length=256)


@router.post("/patients/{pid}/assignments")
def assign_scale(pid: int, data: AssignIn, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request, "assign_scale")
    if data.scale_code not in knowledge.get(db)["scale"]:
        raise HTTPException(404, "Шкала не найдена")
    a = ScaleAssignment(patient_id=p.id, scale_code=data.scale_code, every_days=data.every_days, next_due=date.today(), reason=data.reason)
    db.add(a)
    db.commit()
    return {"id": a.id}


# --- сообщения -------------------------------------------------------------
@router.get("/patients/{pid}/messages")
def messages(pid: int, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request, "messages")
    msgs = db.scalars(select(Message).where(Message.patient_id == p.id).order_by(Message.created_at)).all()
    unread = [m.id for m in msgs if m.sender_role == "patient" and m.read_at is None]
    if unread:
        t = now()
        defer_write(db, lambda w: w.execute(update(Message).where(Message.id.in_(unread)).values(read_at=t)))
    return [services.message_dict(m) for m in msgs]


@router.post("/patients/{pid}/messages")
def send(pid: int, data: services.MessageIn, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request, "message")
    m, _ = services.send_message(db, p, user, data, request.state.received_at)
    alerts.commit(db)
    return {"id": m.id}


# --- алерты --------------------------------------------------------------
@router.get("/alerts")
def list_alerts(status: str = "open", user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    stmt = select(Alert).where((Alert.doctor_id == user.id) | (Alert.escalated_to == user.id))
    if status == "open":
        stmt = stmt.where(Alert.status != "resolved")
    rank = {"critical": 0, "high": 1, "medium": 2}
    items = db.scalars(stmt.order_by(Alert.created_at.desc()).limit(200)).all()
    items.sort(key=lambda a: (rank.get(a.severity, 9), a.status != "new"))
    return [alerts.alert_dict(a, db.get(Patient, a.patient_id)) for a in items]


def _alert(user: User, aid: int, db: Session) -> Alert:
    a = db.get(Alert, aid)
    if not a or (a.doctor_id != user.id and a.escalated_to != user.id):
        raise HTTPException(404, "Алерт не найден")
    return a


@router.post("/alerts/{aid}/delivered")
def alert_delivered(aid: int, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """Квитанция клиента о получении — документирование доставки (193н п. 46 «д»)."""
    a = _alert(user, aid, db)
    if a.delivered_at is None:
        a.delivered_at = now()
        db.commit()
    return {"delivery_ms": round((a.delivered_at - a.data_received_at).total_seconds() * 1000)}


@router.post("/alerts/{aid}/ack")
def alert_ack(aid: int, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    a = _alert(user, aid, db)
    if a.status == "new":
        a.status, a.acknowledged_at, a.acknowledged_by = "acknowledged", now(), user.id
        a.delivered_at = a.delivered_at or a.acknowledged_at
        auth.audit(db, user, "alert_ack", "alert", a.id, patient_id=a.patient_id, ip=auth.client_ip(request))
        db.commit()
    return alerts.alert_dict(a)


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=3, max_length=2000)


@router.post("/alerts/{aid}/resolve")
def alert_resolve(aid: int, data: ResolveIn, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    a = _alert(user, aid, db)
    a.status, a.resolved_at = "resolved", now()
    a.acknowledged_at = a.acknowledged_at or now()
    a.resolution = data.resolution
    auth.audit(db, user, "alert_resolved", "alert", a.id, patient_id=a.patient_id, ip=auth.client_ip(request))
    p = db.get(Patient, a.patient_id)
    alerts.process(db, p, f"resolve:{a.id}", suppress=frozenset({a.rule_id}))  # пересчёт риска
    alerts.commit(db)
    return alerts.alert_dict(a)


class AeReviewIn(BaseModel):
    # Решение врача: описана ли реакция в инструкции (влияет на извещение по приказу № 3518).
    # Не передано — остаётся оценка системы.
    expected: bool | None = None
    serious: bool | None = None


@router.post("/adverse-events/{eid}/review")
def review_adverse_event(eid: int, request: Request, data: AeReviewIn | None = None,
                         user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """Зафиксировать врачебный разбор нежелательного явления; самостоятельных клинических действий нет."""
    ae = db.get(AdverseEvent, eid)
    if not ae:
        raise HTTPException(404, "Нежелательное явление не найдено")
    patient = _p(user, ae.patient_id, db, request, "ae_review")
    data = data or AeReviewIn()
    if ae.status != "reviewed":
        system_expected = ae.expected
        if data.expected is not None:
            ae.expected = data.expected
        if data.serious is not None:
            ae.serious = data.serious
        ae.status = "reviewed"
        auth.audit(db, user, "adverse_event_reviewed", "adverse_event", ae.id,
                   patient_id=patient.id, ip=auth.client_ip(request), expected=ae.expected,
                   system_expected=system_expected, serious=ae.serious)
        alerts.process(db, patient, f"ae-review:{ae.id}")
        alerts.commit(db)
    return {"ok": True, "id": ae.id, "status": ae.status}


# --- очередь решений врача ---------------------------------------------------
def action_dict(a: ClinicalAction) -> dict:
    return {"id": a.id, "patient_id": a.patient_id, "kind": a.kind, "level": a.level, "title": a.title, "payload": a.payload,
            "sources": a.sources, "status": a.status, "due_at": a.due_at, "alert_id": a.alert_id,
            "decided_at": a.decided_at, "comment": a.comment, "created_at": a.created_at}


@router.get("/actions")
def list_actions(status: str = "proposed", user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    rows = db.execute(select(ClinicalAction, Patient).join(Patient, Patient.id == ClinicalAction.patient_id).where(
        Patient.doctor_id == user.id, ClinicalAction.status == status).order_by(ClinicalAction.created_at.desc())).all()
    return [{**action_dict(a), "patient_name": p.full_name} for a, p in rows]


class DecideIn(BaseModel):
    decision: str = Field(pattern="^(confirm|reject)$")
    comment: str | None = Field(None, max_length=2000)


@router.post("/actions/{aid}/decide")
def decide(aid: int, data: DecideIn, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    a = db.get(ClinicalAction, aid)
    if not a:
        raise HTTPException(404, "Действие не найдено")
    p = _p(user, a.patient_id, db, request, "decide")
    if a.status != "proposed":
        raise HTTPException(409, "Решение уже принято")
    a.status = "confirmed" if data.decision == "confirm" else "rejected"
    a.decided_by, a.decided_at = user.id, now()
    a.comment = data.comment
    if a.status == "confirmed" and a.kind == "hold_therapy":
        for rx in db.scalars(select(Prescription).where(Prescription.patient_id == p.id, Prescription.status == "active")):
            rx.status = "paused"
        alerts.emit(db, patient_channel(p.id), "therapy_changed", {})
    if a.status == "confirmed" and a.kind == "referral":
        alerts.emit(db, patient_channel(p.id), "referral", {"level": a.level})
    auth.audit(db, user, f"action_{a.status}", "clinical_action", a.id, patient_id=p.id, kind=a.kind, level=a.level)
    alerts.commit(db)
    return action_dict(a)


@router.get("/actions/{aid}/pv-report")
def pv_report(aid: int, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """Черновик сообщения о нежелательной реакции (Порядок фармаконадзора, приказ Росздравнадзора
    от 17.06.2024 № 3518, действует с 01.03.2025; заменил приказ № 1071)."""
    a = db.get(ClinicalAction, aid)
    if not a or a.kind != "pv_report":
        raise HTTPException(404, "Извещение не найдено")
    p = _p(user, a.patient_id, db, request, "pv_report")
    kb = knowledge.get(db)
    source_ae_id = (a.payload or {}).get("adverse_event_id")
    ae = db.get(AdverseEvent, source_ae_id) if isinstance(source_ae_id, int) else None
    if ae is not None and ae.patient_id != p.id:
        # Never allow a malformed action payload to cross patient boundaries.
        raise HTTPException(409, "Извещение связано с другим пациентом")
    if ae is None:
        # Backward compatibility for actions created before adverse_event_id was recorded.
        ae = db.scalar(select(AdverseEvent).where(AdverseEvent.patient_id == p.id).order_by(AdverseEvent.created_at.desc()))
    rx = db.get(Prescription, ae.prescription_id) if ae and ae.prescription_id else None
    drug = kb["drug"].get(rx.drug_id, {}) if rx else {}
    doctor = db.get(User, p.doctor_id)
    severe = bool(ae and (ae.life_threatening or ae.serious))
    known_at = ae.created_at if ae else a.created_at  # п. 24: срок — со дня, когда сведения стали известны
    if ae and ae.life_threatening:
        deadline, rule, mandatory = services.add_business_days(known_at, 3), "Серьёзная НР с летальным исходом или угрозой жизни — не позднее 3 рабочих дней (п. 21)", True
    elif severe:
        deadline, rule, mandatory = known_at + timedelta(days=15), "Серьёзная НР — не позднее 15 календарных дней (п. 22)", True
    else:
        deadline, rule, mandatory = None, "Несерьёзная НР: обязательное сообщение в Росздравнадзор не требуется, учёт — по внутреннему порядку медицинской организации (п. 20); сообщение может быть направлено добровольно", False
    db.commit()
    return {
        "form": "Сообщение о нежелательной реакции лекарственного препарата",
        "legal_basis": "Порядок фармаконадзора лекарственных препаратов для медицинского применения, приказ Росздравнадзора от 17.06.2024 № 3518",
        "mandatory": mandatory,
        "deadline": deadline,
        "deadline_rule": rule,
        "patient": {"code": p.code, "sex": p.sex, "age": context.age(p.birth_date)},  # обезличено
        "suspected_drug": drug and {"trade_name": drug.get("trade_name"), "inn": drug.get("inn"),
                                    "registration": drug.get("registration"), "regimen": rx.regimen, "started_at": rx.started_at},
        "concomitant": p.current_meds,
        "reaction": ae and {"title": ae.title, "intensity": ae.intensity, "serious": ae.serious, "life_threatening": ae.life_threatening,
                            "expected_by_instruction": ae.expected, "onset": ae.created_at, "description": ae.description},
        "additional_monitoring": drug.get("additional_monitoring", False),
        "reporter": {"full_name": doctor.full_name, "specialty": doctor.specialty},
        "submit_to": "АИС Росздравнадзора (п. 7); при технической невозможности — по электронной почте (пп. 8, 10); копия — в медицинскую документацию пациента (п. 25)",
        "severe": severe,
    }


# --- документы: извлечение данных из истории болезни ----------------------------
class DocumentIn(BaseModel):
    filename: str = Field(max_length=256)
    text: str = Field(min_length=10, max_length=200_000)


@router.post("/patients/{pid}/documents")
def upload_document(pid: int, data: DocumentIn, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request, "document_upload")
    result = extract.extract(data.text, knowledge.get(db))
    d = Document(patient_id=p.id, filename=data.filename, extracted=result["data"], extractor=result["extractor"],
                 extraction_ms=result["elapsed_ms"], uploaded_by=user.id)
    db.add(d)
    d.text = data.text
    db.commit()
    return {"id": d.id, **result}


@router.post("/documents/{did}/apply")
def apply_document(did: int, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """Врач проверил извлечённые данные и переносит их в карточку."""
    d = db.get(Document, did)
    if not d:
        raise HTTPException(404, "Документ не найден")
    p = _p(user, d.patient_id, db, request, "document_apply")
    ex = d.extracted
    known = {x["icd10"] for x in p.diagnoses}
    p.diagnoses = p.diagnoses + [x for x in ex.get("diagnoses", []) if x["icd10"] not in known]
    known_m = {(m.get("inn") or m.get("name")) for m in p.current_meds}
    p.current_meds = p.current_meds + [m for m in _normalize_meds(db, ex.get("medications", [])) if (m.get("inn") or m.get("name")) not in known_m]
    known_h = {c["inn"] for c in p.therapy_history}
    p.therapy_history = p.therapy_history + [{"inn": m["inn"], "dose": m.get("dose"), "weeks": None, "outcome": "unknown"}
                                             for m in ex.get("past_medications", []) if m.get("inn") and m["inn"] not in known_h]
    prof = dict(p.profile)
    for k in ("conditions", "allergies"):
        prof[k] = sorted(set(prof.get(k, [])) | set(ex.get(k, [])))
    for k in ("egfr", "child_pugh", "pregnant", "post_covid"):
        if ex.get(k) is not None:
            prof[k] = ex[k]
    p.profile = prof
    d.applied = True
    auth.audit(db, user, "document_applied", "document", d.id, patient_id=p.id)
    alerts.process(db, p, f"doc:{d.id}")
    alerts.commit(db)
    return {"ok": True}


# --- сводка перед визитом, FHIR --------------------------------------------
@router.get("/patients/{pid}/summary")
def summary(pid: int, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request, "summary")
    ctx = context.build(db, p)
    kb = knowledge.get(db)
    lines = []
    for code, v in ctx["scales"].items():
        title = kb["scale"].get(code, {}).get("title", code).split(" — ")[0]
        trend = "" if v["delta"] is None else f" ({'+' if v['delta'] > 0 else ''}{v['delta']} к прошлой)"
        base = "" if v["change_from_baseline_pct"] is None else f", {v['change_from_baseline_pct']}% от исходного"
        lines.append(f"{title}: {v['score']} — {v['band'].lower()}{trend}{base}")
    if ctx["therapy"]["active_drugs"]:
        lines.append(f"Терапия: {', '.join(kb['drug'][d]['trade_name'] for d in ctx['therapy']['active_drugs'])}, "
                     f"{ctx['therapy']['weeks_on_current']} нед.")
    if ctx["adherence"]["pct_14d"] is not None:
        lines.append(f"Приверженность за 14 дней: {ctx['adherence']['pct_14d']}%")
    if ctx["diary"]["mood_avg_7d"] is not None:
        lines.append(f"Дневник (7 дн.): настроение {ctx['diary']['mood_avg_7d']}/10, тревога {ctx['diary']['anxiety_avg_7d']}/10, "
                     f"сон {ctx['diary']['sleep_avg_7d']} ч")
    if ctx["ae"]["open_count"]:
        lines.append(f"Нежелательные явления: {ctx['ae']['open_count']} (последнее — {ctx['ae']['last_title']})")
    db.commit()
    return {"text": "\n".join(lines), "generated": "по данным наблюдения, без ИИ"}


@router.get("/patients/{pid}/fhir")
def fhir_export(pid: int, request: Request, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    p = _p(user, pid, db, request, "fhir_export")
    bundle = fhir.bundle(db, p)
    db.commit()
    return bundle


@router.get("/stream")
async def stream(ticket: str, request: Request, last_event_id: int | None = None, db: Session = Depends(get_db)):
    def _redeem_in_worker(value: str):
        from ..db import SessionLocal
        with SessionLocal() as ticket_db:
            return auth.redeem_ticket(value, ticket_db)
    user = await asyncio.to_thread(_redeem_in_worker, ticket)
    if user.role != "doctor":
        raise HTTPException(403, "Недостаточно прав")
    db.close()
    return sse(doctor_channel(user.id), _last_id(request, last_event_id))
