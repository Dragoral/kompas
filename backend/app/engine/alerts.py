"""Алертинг: вычисление правил при каждом поступлении данных от пациента.

Последовательность: данные сохранены -> контекст -> правила -> алерт в БД ->
мгновенная публикация врачу (SSE) -> автоматические немедицинские действия
(кризисный экран, внеплановая шкала, предложения врачу). Клинические действия
только предлагаются (ClinicalAction со статусом proposed).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import bus
from ..bus import doctor_channel, patient_channel
from ..models import Alert, ClinicalAction, Patient, ScaleAssignment, now
from . import context, knowledge, logic, recommend

SEV_RANK = {"critical": 3, "high": 2, "medium": 1}


def _action_name(a) -> str:
    return a if isinstance(a, str) else next(iter(a))


def _resolve(v, ctx):
    return logic.get_var(ctx, v) if isinstance(v, str) else v


def _action_arg(a):
    return None if isinstance(a, str) else next(iter(a.values()))


def process(db: Session, patient: Patient, trigger_ref: str, received_at: datetime | None = None) -> list[Alert]:
    """Вызывается после сохранения любых данных пациента. Возвращает новые алерты."""
    received_at = received_at or now()
    kb = knowledge.get(db)
    ctx = context.build(db, patient)
    created: list[Alert] = []

    open_alerts = db.scalars(select(Alert).where(Alert.patient_id == patient.id, Alert.status != "resolved")).all()
    open_by_rule = {a.rule_id: a for a in open_alerts}

    for rule in kb["rules"].get("alerts", {}).get("rules", []):
        if not logic.evaluate(rule["when"], ctx):
            continue
        existing = open_by_rule.get(rule["id"])
        # Повторно не дублируем открытый алерт; критические — на каждое новое событие
        if existing and (rule["severity"] != "critical" or existing.trigger_ref == trigger_ref):
            continue
        actions = rule.get("actions", [])
        alert = Alert(
            patient_id=patient.id,
            doctor_id=patient.doctor_id,
            rule_id=rule["id"],
            severity=rule["severity"],
            title=rule["title"],

            source=rule.get("source"),
            actions=actions,
            trigger_ref=trigger_ref,
            data_received_at=received_at,
            escalate_after_min=next((_resolve(_action_arg(a)["after_min"], ctx) for a in actions if _action_name(a) == "escalate"), None),
        )
        db.add(alert)
        db.flush()
        alert.message = logic.render(rule.get("message", rule["title"]), ctx)
        _run_actions(db, patient, alert, actions)
        created.append(alert)

    _sync_referral(db, patient, ctx, kb)
    patient.risk_score = risk_score(ctx, open_alerts + created)
    db.flush()
    t = now()
    for alert in created:  # события — в той же транзакции, что и данные (transactional outbox)
        alert.pushed_at = t
        bus.enqueue(db, doctor_channel(alert.doctor_id), "alert", alert_event(alert))
        if any(_action_name(a) == "crisis_screen" for a in alert.actions):
            bus.enqueue(db, patient_channel(patient.id), "crisis", {"alert_id": alert.id})
    return created


def commit(db: Session) -> None:
    db.commit()


def alert_event(a: Alert) -> dict:
    """В очередь событий — только идентификаторы и тип; подробности клиент берёт по API с проверкой прав."""
    return {"id": a.id, "patient_id": a.patient_id, "severity": a.severity, "rule_id": a.rule_id, "title": a.title}


def emit(db: Session, channel: str, event: str, data: dict) -> None:
    bus.enqueue(db, channel, event, data)


def _run_actions(db: Session, patient: Patient, alert: Alert, actions: list) -> None:
    for a in actions:
        name, arg = _action_name(a), _action_arg(a)
        if name == "request_scale":
            db.add(ScaleAssignment(patient_id=patient.id, scale_code=arg, every_days=None, next_due=date.today(),
                                   reason=f"Внеплановая оценка: {alert.title}"))
        elif name in ("propose_visit", "propose_hold_therapy", "pharmacovigilance_draft"):
            kind = {"propose_visit": "visit", "propose_hold_therapy": "hold_therapy", "pharmacovigilance_draft": "pv_report"}[name]
            dup = db.scalar(select(ClinicalAction).where(ClinicalAction.patient_id == patient.id, ClinicalAction.kind == kind,
                                                         ClinicalAction.status == "proposed"))
            if dup:
                continue
            title = {"visit": "Внеплановый визит", "hold_therapy": "Приостановить терапию до осмотра",
                     "pv_report": "Извещение о нежелательной реакции (Росздравнадзор)"}[kind]
            db.add(ClinicalAction(patient_id=patient.id, kind=kind, title=f"{title}: {alert.title}", alert_id=alert.id,
                                  payload={"reason": alert.message}, sources=[alert.source] if alert.source else []))


def _sync_referral(db: Session, patient: Patient, ctx: dict, kb: dict) -> None:
    r = recommend.routing(ctx, kb)
    if not r or not r["level"]:
        return
    existing = db.scalars(select(ClinicalAction).where(ClinicalAction.patient_id == patient.id, ClinicalAction.kind == "referral",
                                                       ClinicalAction.status.in_(["proposed", "confirmed"]))).all()
    if any(e.level == "mandatory" or e.level == r["level"] for e in existing):
        return
    for e in existing:  # повышение уровня: desirable -> mandatory
        if e.status == "proposed":
            e.status, e.comment = "rejected", "Заменено направлением более высокого уровня"
    title = "Направление к психиатру: " + ("ОБЯЗАТЕЛЬНО" if r["level"] == "mandatory" else "ЖЕЛАТЕЛЬНО")
    db.add(ClinicalAction(patient_id=patient.id, kind="referral", level=r["level"], title=title,
                          payload={"reasons": r["reasons"]}, sources=sorted({x["source"] for x in r["reasons"] if x.get("source")})))


def risk_score(ctx: dict, alerts: list[Alert]) -> int:
    """Балл для автотриажа списка пациентов (чем выше — тем раньше в списке)."""
    s = 0
    for a in alerts:
        if a.status != "resolved":
            s += {"critical": 100, "high": 30, "medium": 10}.get(a.severity, 0)
    for v in ctx["scales"].values():
        s += v.get("severity", 0) * 5
    return s


def alert_dict(a: Alert, patient: Patient | None = None) -> dict:
    return {
        "id": a.id, "patient_id": a.patient_id, "patient_name": patient.full_name if patient else None,
        "rule_id": a.rule_id, "severity": a.severity, "title": a.title, "message": a.message, "source": a.source,
        "actions": [_action_name(x) for x in a.actions], "status": a.status,
        "created_at": a.created_at, "data_received_at": a.data_received_at, "pushed_at": a.pushed_at,
        "delivered_at": a.delivered_at, "acknowledged_at": a.acknowledged_at, "escalated_to": a.escalated_to,
    }
