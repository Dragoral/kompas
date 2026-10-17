"""Обезличенная аналитика по клинике (агрегаты).

* Только агрегаты, без идентификаторов и псевдонимов пациентов.
* k-анонимность: группа меньше K_MIN пациентов показывается как «< K_MIN»
  (подавление малых ячеек), чтобы по статистике нельзя было выделить человека.
* Доступ — администратор и клинический рецензент; каждый запрос пишется в журнал.
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..db import get_db
from ..engine import context, knowledge
from ..models import AdverseEvent, Alert, Patient, Prescription, User, now

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
K_MIN = 5


def allowed(user: User = Depends(auth.current_user)) -> User:
    if user.role == "admin" or (user.role == "doctor" and user.is_reviewer):
        return user
    raise HTTPException(403, "Недостаточно прав")


def _cell(n: int, k: int):
    return n if n >= k else f"< {k}"


def _group(icd: str) -> str:
    for prefix, title in (("F41.1", "ГТР (F41.1)"), ("F41", "Другие тревожные (F41)"), ("F32", "Депрессия (F32–F33)"),
                          ("F33", "Депрессия (F32–F33)"), ("F43", "Реакция на стресс, расстройства адаптации (F43)")):
        if icd.startswith(prefix):
            return title
    return "Прочие"


@router.get("/summary")
def summary(days: int = Query(90, ge=7, le=3650), k: int = Query(K_MIN, ge=K_MIN, le=50),
            user: User = Depends(allowed), db: Session = Depends(get_db)):
    since = now() - timedelta(days=days)
    kb = knowledge.get(db)
    patients = db.scalars(select(Patient).where(Patient.erased_at.is_(None))).all()
    by_dx: dict[str, int] = {}
    by_drug: dict[str, dict] = {}
    adherence = []
    for p in patients:
        dx = next((d["icd10"] for d in p.diagnoses if d.get("primary")), (p.diagnoses or [{"icd10": "—"}])[0]["icd10"])
        by_dx[_group(dx)] = by_dx.get(_group(dx), 0) + 1
        ctx = context.build(db, p)
        if ctx["adherence"]["pct_14d"] is not None:
            adherence.append(ctx["adherence"]["pct_14d"])
        rx = db.scalar(select(Prescription).where(Prescription.patient_id == p.id, Prescription.status == "active"))
        if rx:
            d = by_drug.setdefault(rx.drug_id, {"patients": 0, "responders": 0, "assessed": 0})
            d["patients"] += 1
            sc = ctx["scales"].get("HAMA") or ctx["scales"].get("GAD7")
            if sc and sc["change_from_baseline_pct"] is not None:
                d["assessed"] += 1
                d["responders"] += sc["change_from_baseline_pct"] <= -50
    aes = db.scalars(select(AdverseEvent).where(AdverseEvent.created_at >= since)).all()
    ae_by_drug: dict[str, dict] = {}
    for a in aes:
        rx = db.get(Prescription, a.prescription_id) if a.prescription_id else None
        key = rx.drug_id if rx else "без активной терапии"
        e = ae_by_drug.setdefault(key, {"total": 0, "serious": 0, "unexpected": 0})
        e["total"] += 1
        e["serious"] += bool(a.serious)
        e["unexpected"] += a.expected is False
    alerts = db.scalars(select(Alert).where(Alert.created_at >= since)).all()
    by_rule: dict[str, int] = {}
    for a in alerts:
        by_rule[a.title] = by_rule.get(a.title, 0) + 1
    ack = [(a.acknowledged_at - a.created_at).total_seconds() / 60 for a in alerts if a.acknowledged_at]
    auth.audit(db, user, "analytics_viewed", "analytics", None, days=days, k=k)
    db.commit()
    name = lambda d: kb["drug"].get(d, {}).get("trade_name", d)
    return {
        "period_days": days, "k_anonymity": k,
        "note": f"Обезличенные агрегаты; группы меньше {k} пациентов скрыты",
        "patients_total": _cell(len(patients), k),
        "patients_by_diagnosis": {g: _cell(n, k) for g, n in sorted(by_dx.items())},
        "therapy": [{"drug": name(d), "patients": _cell(v["patients"], k),
                     "response_rate_pct": round(v["responders"] * 100 / v["assessed"]) if v["assessed"] >= k else None,
                     "response_definition": "снижение HAM-A (или GAD-7) ≥ 50% от исходного"}
                    for d, v in sorted(by_drug.items())],
        "adherence_median_pct": statistics.median(adherence) if len(adherence) >= k else None,
        "adverse_events": [{"drug": name(d), "total": _cell(v["total"], k), "serious": _cell(v["serious"], k),
                            "unexpected": _cell(v["unexpected"], k)} for d, v in sorted(ae_by_drug.items())],
        "alerts_by_type": {t: _cell(n, k) for t, n in sorted(by_rule.items())},
        "alert_ack_median_min": round(statistics.median(ack), 1) if len(ack) >= k else None,
    }
