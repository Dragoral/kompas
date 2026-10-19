"""Сборка «контекста пациента» — плоского словаря, по которому вычисляются все
правила (алерты, маршрутизация, противопоказания). Список доступных переменных
описан в docs/rules.md; новые переменные добавляются здесь, а правила — в YAML.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AdverseEvent, DiaryEntry, DoseLog, Message, Patient, Prescription, ScaleAssignment, ScaleResult, User, now
from . import knowledge

# Лексический скрининг высказываний о самоповреждении (финальная оценка — врач).
SELF_HARM = re.compile(
    r"(не\s*хочу\s*жить|покончить\s*с\s*собой|покончу|суицид|убить\s*себя|убью\s*себя|"
    r"лучше\s*бы\s*(я\s*)?умер|хочу\s*умереть|нет\s*смысла\s*жить|выпрыгну|наглотаюсь|порезать\s*себя|самоповрежд)",
    re.IGNORECASE,
)


def age(born: date, today: date | None = None) -> int:
    t = today or date.today()
    return t.year - born.year - ((t.month, t.day) < (born.month, born.day))


def build(db: Session, patient: Patient, at: datetime | None = None) -> dict:
    at = at or now()
    kb = knowledge.get(db)
    prof = patient.profile or {}
    doctor = db.get(User, patient.doctor_id)

    ctx: dict = {
        "patient": {
            "id": patient.id,
            "age": age(patient.birth_date, at.date()),
            "sex": patient.sex,
            "pregnant": bool(prof.get("pregnant")),
            "lactating": bool(prof.get("lactating")),
            "egfr": prof.get("egfr"),
            "child_pugh": prof.get("child_pugh"),
            "conditions": sorted(set(prof.get("conditions", [])) | conditions_from_icd(kb, patient.diagnoses or [])),
            "allergies": list(prof.get("allergies", [])),
            "post_covid": bool(prof.get("post_covid")),
            "drives_professionally": bool(prof.get("drives_professionally")),
            "psychotherapy": prof.get("psychotherapy"),
            "icd10": [d["icd10"] for d in patient.diagnoses or []],
        },
        "doctor": {"id": doctor.id, "specialty": doctor.specialty},
        "thresholds": thresholds(kb, patient),
        "monitoring": {"active": patient.monitoring_active, "in_person_visit": patient.in_person_visit_at is not None},
    }

    # Текущая сопутствующая терапия -> фармакологические классы
    by_class: dict[str, list[str]] = {}
    for m in patient.current_meds or []:
        cls = m.get("classes") or knowledge.classes_for(kb, m.get("inn") or m.get("name", ""))[1]
        for c in cls:
            by_class.setdefault(c, []).append(m.get("name") or m.get("inn"))
    if prof.get("alcohol_use"):
        by_class.setdefault("alcohol", []).append("алкоголь")
    maoi_days = (at.date() - patient.maoi_stopped_at).days if patient.maoi_stopped_at else None
    ctx["meds"] = {"classes": sorted(by_class), "by_class": by_class, "maoi_stopped_days_ago": maoi_days}
    ctx["history"] = {"courses": list(patient.therapy_history or [])}

    # Шкалы: последнее значение, предыдущее, исходное, динамика
    scales: dict = {}
    rows = db.scalars(
        select(ScaleResult).where(ScaleResult.patient_id == patient.id, ScaleResult.created_at <= at).order_by(ScaleResult.created_at)
    ).all()
    by_code: dict[str, list[ScaleResult]] = {}
    for r in rows:
        by_code.setdefault(r.scale_code, []).append(r)
    observed: dict[str, datetime] = {}
    for code, rs in by_code.items():
        last, prev, first = rs[-1], (rs[-2] if len(rs) > 1 else None), rs[0]
        base = first
        rx = _active_rx(db, patient.id)
        if rx:  # исходный уровень — последнее измерение до начала текущей терапии
            before = [r for r in rs if r.created_at <= rx.started_at]
            base = before[-1] if before else first
        scales[code] = {
            "score": last.score,
            "band": last.band,
            "severity": last.severity,
            "items": {str(k): v for k, v in last.answers.items()},
            "subscales": {k: v.get("score") for k, v in ((last.details or {}).get("subscales") or {}).items()},
            "prev_score": prev.score if prev else None,
            "delta": (last.score - prev.score) if prev else None,
            "baseline": base.score,
            "change_from_baseline_pct": round((last.score - base.score) * 100 / base.score) if base.score and base is not last else None,
            "days_ago": (at - last.created_at).days,
            "count": len(rs),
        }
        observed[f"scales.{code}"] = last.created_at
    ctx["scales"] = scales

    # Дневник
    diary = db.scalars(
        select(DiaryEntry).where(DiaryEntry.patient_id == patient.id, DiaryEntry.day <= at.date()).order_by(DiaryEntry.day.desc()).limit(14)
    ).all()
    week = [d for d in diary if (at.date() - d.day).days < 7]
    ctx["diary"] = {
        "days_since_last": (at.date() - diary[0].day).days if diary else None,
        "mood_avg_7d": _avg([d.mood for d in week]),
        "anxiety_avg_7d": _avg([d.anxiety for d in week]),
        "sleep_avg_7d": _avg([d.sleep_hours for d in week]),
    }

    # Терапия и приверженность
    rx = _active_rx(db, patient.id)
    ctx["therapy"] = {
        "active_drugs": [rx.drug_id] if rx else [],
        "weeks_on_current": ((at - rx.started_at).days // 7) if rx else None,
    }
    since = at - timedelta(days=14)
    doses = db.scalars(
        select(DoseLog).where(DoseLog.patient_id == patient.id, DoseLog.scheduled_for >= since,
                            DoseLog.scheduled_for <= at - timedelta(hours=3))  # 3 ч на приём, потом — пропуск.order_by(DoseLog.scheduled_for)
    ).all()
    taken = sum(1 for d in doses if d.status == "taken")
    streak = 0
    for d in reversed(doses):
        if d.status == "taken":
            break
        streak += 1
    # Выполнение рекомендаций врача: дневник и назначенные шкалы
    window = 14
    if patient.in_person_visit_at:
        window = max(1, min(14, (at.date() - patient.in_person_visit_at.date()).days + 1))
    diary_days = len({d.day for d in diary if (at.date() - d.day).days < window})
    overdue = db.scalars(select(ScaleAssignment).where(
        ScaleAssignment.patient_id == patient.id, ScaleAssignment.active.is_(True),
        ScaleAssignment.next_due < at.date() - timedelta(days=2))).all()
    dose_pct = round(taken * 100 / len(doses)) if doses else None
    diary_pct = round(diary_days * 100 / window) if window >= 3 else None  # первые дни наблюдения не оцениваем
    parts = [x for x in (dose_pct, diary_pct) if x is not None]
    ctx["adherence"] = {
        "pct_14d": dose_pct,
        "missed_streak": streak if doses else None,
        "doses_14d": len(doses),
        "diary_pct": diary_pct,
        "scales_overdue": sorted({a.scale_code for a in overdue}),
        "overall_pct": round(sum(parts) / len(parts)) if parts else None,
    }

    # Нежелательные явления
    aes = db.scalars(
        select(AdverseEvent).where(AdverseEvent.patient_id == patient.id, AdverseEvent.status == "open").order_by(AdverseEvent.created_at.desc())
    ).all()
    ctx["ae"] = {
        "open_count": len(aes),
        "serious_open": any(a.serious or a.intensity == "severe" for a in aes),
        "last_title": aes[0].title if aes else None,
    }

    # Тексты пациента за 3 дня — скрининг высказываний
    recent = at - timedelta(days=3)
    texts = [(d.created_at, d.note) for d in diary if d.note and d.day >= recent.date()]
    texts += [(m.created_at, m.text) for m in db.scalars(
        select(Message).where(Message.patient_id == patient.id, Message.sender_role == "patient", Message.created_at >= recent)
    )]
    hits = sorted(((t, m.group(0)) for t, text in texts if (m := SELF_HARM.search(text))), key=lambda h: h[0])
    quote = hits[-1][1] if hits else None
    ctx["flags"] = {"self_harm_text": quote is not None, "self_harm_quote": quote}
    if hits:
        observed["flags.self_harm_text"] = hits[-1][0]
    # Время появления данных, на которые опираются правила: повторный критический
    # алерт создаётся только на новые данные, а не на каждое событие пациента
    ctx["_observed_at"] = observed
    return ctx


def conditions_from_icd(kb: dict, diagnoses: list[dict]) -> set[str]:
    """Состояния из кодов МКБ-10 (справочник icd_conditions): F10.2 -> зависимость от алкоголя и т. п."""
    mapping = kb["dictionary"].get("icd_conditions", {}).get("map", [])
    codes = [d.get("icd10", "") for d in diagnoses]
    return {m["tag"] for m in mapping for c in codes for prefix in m["codes"] if c.startswith(prefix)}


def thresholds(kb: dict, patient: Patient) -> dict:
    """Пороги алертов: значения по умолчанию из правил + индивидуальные для пациента."""
    defaults = {k: v["default"] for k, v in kb["rules"].get("alerts", {}).get("thresholds", {}).items()}
    return {**defaults, **{k: v for k, v in (patient.alert_thresholds or {}).items() if k in defaults}}


def _active_rx(db: Session, patient_id: int) -> Prescription | None:
    return db.scalar(
        select(Prescription).where(Prescription.patient_id == patient_id, Prescription.status == "active").order_by(Prescription.started_at.desc())
    )


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None
