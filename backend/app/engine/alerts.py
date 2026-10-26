"""Алертинг: вычисление правил при каждом поступлении данных от пациента.

Последовательность: данные сохранены -> контекст -> правила -> алерт в БД ->
мгновенная публикация врачу (SSE) -> автоматические немедицинские действия
(кризисный экран, внеплановая шкала, предложения врачу). Клинические действия
только предлагаются (ClinicalAction со статусом proposed).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import bus, notify
from ..bus import doctor_channel, patient_channel
from ..models import Alert, ClinicalAction, Patient, ScaleAssignment, now
from . import context, knowledge, logic, recommend, variables

SEV_RANK = {"critical": 3, "high": 2, "medium": 1}


def _action_name(a) -> str:
    return a if isinstance(a, str) else next(iter(a))


def _resolve(v, ctx):
    return logic.get_var(ctx, v) if isinstance(v, str) else v


def _action_arg(a):
    return None if isinstance(a, str) else next(iter(a.values()))


def process(db: Session, patient: Patient, trigger_ref: str, received_at: datetime | None = None,
            suppress: frozenset[str] = frozenset()) -> list[Alert]:
    """Вызывается после сохранения любых данных пациента. Возвращает новые алерты.
    suppress — правила, которые не создают алерт в этом пересчёте (только что закрытые врачом)."""
    received_at = received_at or now()
    kb = knowledge.get(db)
    ctx = context.build(db, patient)
    created: list[Alert] = []

    alert_history = db.scalars(
        select(Alert).where(Alert.patient_id == patient.id).order_by(Alert.created_at.desc(), Alert.id.desc())
    ).all()
    open_alerts = [a for a in alert_history if a.status != "resolved"]
    open_by_rule = {}
    latest_by_rule = {}
    for a in alert_history:  # результат уже отсортирован от нового к старому
        latest_by_rule.setdefault(a.rule_id, a)
        if a.status != "resolved":
            open_by_rule.setdefault(a.rule_id, a)

    for rule in kb["rules"].get("alerts", {}).get("rules", []):
        if rule["id"] in suppress or not logic.safe_eval(rule["when"], ctx, f"alerts:{rule.get('id')}"):
            continue
        existing = open_by_rule.get(rule["id"])
        latest = latest_by_rule.get(rule["id"])
        # Закрытый алерт не создаётся заново на тех же данных. Новый алерт допустим
        # только когда источник правила обновился после закрытия предыдущего.
        if existing and not (rule["severity"] == "critical" and _new_evidence(rule, ctx, existing)):
            continue
        if existing and rule["severity"] != "critical":
            continue
        if not existing and latest and latest.status == "resolved" and not _may_repeat_after_resolve(rule, ctx, latest):
            continue
        actions = rule.get("actions", [])
        alert = Alert(
            patient_id=patient.id,
            doctor_id=patient.doctor_id,
            rule_id=rule["id"],
            rules_version=kb["versions"].get(("rules", "alerts"), 1),
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
        # Если несколько новых критических событий поступили в одном пересчёте,
        # учитываем уже созданный алерт как открытый, не создавая дубль тем же проходом.
        open_by_rule[rule["id"]] = alert
        latest_by_rule[rule["id"]] = alert

    _sync_referral(db, patient, ctx, kb)
    patient.risk_score = risk_score(ctx, open_alerts + created)
    db.flush()
    t = now()
    for alert in created:  # события — в той же транзакции, что и данные (transactional outbox)
        alert.pushed_at = t
        bus.enqueue(db, doctor_channel(alert.doctor_id), "alert", alert_event(alert))
        if any(_action_name(a) == "crisis_screen" for a in alert.actions):
            bus.enqueue(db, patient_channel(patient.id), "crisis", {"alert_id": alert.id})
        if alert.severity == "critical":  # экстренное оповещение по политике клиники
            alert.notified = notify.route_critical(db, kb, alert, patient)
            if alert.escalated_to:  # вне рабочего времени — сразу дежурному
                bus.enqueue(db, doctor_channel(alert.escalated_to), "alert", {**alert_event(alert), "escalated": True})
    return created


def commit(db: Session) -> None:
    db.commit()


def alert_event(a: Alert) -> dict:
    """В очередь событий — только идентификаторы и тип; подробности клиент берёт по API с проверкой прав."""
    return {"id": a.id, "patient_id": a.patient_id, "severity": a.severity, "rule_id": a.rule_id, "title": a.title}


def emit(db: Session, channel: str, event: str, data: dict) -> None:
    bus.enqueue(db, channel, event, data)


# --- реестр действий алертов -------------------------------------------------------
# Действие = функция (db, patient, alert, arg). Новое действие добавляется сюда одной
# функцией, после чего его можно использовать в правилах (справочник rules/alerts).
# notify_doctor, crisis_screen, escalate выполняются ядром (события, оповещения, эскалация).

def _propose(kind: str, title: str):
    def act(db: Session, patient: Patient, alert: Alert, arg) -> None:
        source_ae_id = None
        if kind == "pv_report" and alert.trigger_ref and alert.trigger_ref.startswith("ae:"):
            try:
                source_ae_id = int(alert.trigger_ref.split(":", 1)[1])
            except ValueError:
                source_ae_id = None
        stmt = select(ClinicalAction).where(
            ClinicalAction.patient_id == patient.id,
            ClinicalAction.kind == kind,
            ClinicalAction.status == "proposed",
        )
        if source_ae_id is not None:
            stmt = stmt.where(ClinicalAction.payload["adverse_event_id"].as_integer() == source_ae_id)
        dup = db.scalar(stmt)
        if dup:
            return
        payload = {"alert_id": alert.id, "rule_id": alert.rule_id}
        if source_ae_id is not None:
            payload["adverse_event_id"] = source_ae_id
        # В payload — только идентификаторы, без свободного текста пациента.
        db.add(ClinicalAction(patient_id=patient.id, kind=kind, title=f"{title}: {alert.title}", alert_id=alert.id,
                              payload=payload, sources=[alert.source] if alert.source else []))
    return act


def _evidence_at(rule: dict, ctx: dict) -> datetime | None:
    observed = ctx.get("_observed_at", {})
    times = [observed.get(".".join(path.split(".")[:2])) for path in variables.referenced(rule["when"])]
    times = [t for t in times if t is not None]
    return max(times) if times else None


def _new_evidence(rule: dict, ctx: dict, existing: Alert) -> bool:
    t = _evidence_at(rule, ctx)
    return t is not None and t > existing.created_at


# Закрытое врачом оповещение по правилу без отметок времени в данных (например, «нет ответа
# на терапию») повторяется не раньше этого срока, если состояние сохраняется.
RESOLVED_QUIET = timedelta(days=7)


def _may_repeat_after_resolve(rule: dict, ctx: dict, resolved: Alert) -> bool:
    closed_at = resolved.resolved_at or resolved.acknowledged_at or resolved.created_at
    t = _evidence_at(rule, ctx)
    if t is not None:
        return t > closed_at
    return now() - closed_at >= RESOLVED_QUIET


def _request_scale(db: Session, patient: Patient, alert: Alert, arg) -> None:
    pending = db.scalar(select(ScaleAssignment.id).where(
        ScaleAssignment.patient_id == patient.id, ScaleAssignment.scale_code == arg, ScaleAssignment.active.is_(True),
        ScaleAssignment.every_days.is_(None), ScaleAssignment.next_due <= date.today()))
    if pending:  # внеплановая оценка уже назначена и ещё не пройдена
        return
    db.add(ScaleAssignment(patient_id=patient.id, scale_code=arg, every_days=None, next_due=date.today(),
                           reason=f"Внеплановая оценка: {alert.title}"))


def _core(db, patient, alert, arg) -> None:
    """Выполняется ядром при создании алерта (см. process)."""


ACTIONS = {
    "notify_doctor": _core,
    "crisis_screen": _core,
    "escalate": _core,
    "request_scale": _request_scale,
    "propose_visit": _propose("visit", "Внеплановый визит"),
    "propose_hold_therapy": _propose("hold_therapy", "Приостановить терапию до осмотра"),
    "pharmacovigilance_draft": _propose("pv_report", "Сообщение о нежелательной реакции (Росздравнадзор)"),
}


def _run_actions(db: Session, patient: Patient, alert: Alert, actions: list) -> None:
    for a in actions:
        name, arg = _action_name(a), _action_arg(a)
        fn = ACTIONS.get(name)
        if fn is None:
            from ..observability import report_problem
            report_problem("alert_action", f"{alert.rule_id}:{name}", "неизвестное действие — пропущено")
            continue
        fn(db, patient, alert, arg)


def _sync_referral(db: Session, patient: Patient, ctx: dict, kb: dict) -> None:
    """Предложения врачу по каждой цели маршрутизации (только предложения — решает врач)."""
    r = recommend.routing(ctx, kb)
    if not r:
        return
    existing = db.scalars(select(ClinicalAction).where(ClinicalAction.patient_id == patient.id, ClinicalAction.kind == "referral",
                                                       ClinicalAction.status.in_(["proposed", "confirmed"]))).all()
    for route in r["routes"]:
        if not route["level"]:
            continue
        same = [e for e in existing if (e.payload or {}).get("target", "psychiatrist") == route["target"]]
        if any(e.level == "mandatory" or e.level == route["level"] for e in same):
            continue
        for e in same:  # повышение уровня: желательно -> обязательно
            if e.status == "proposed":
                e.status = "rejected"
                e.comment = "Заменено направлением более высокого уровня"
        mark = "ОБЯЗАТЕЛЬНО" if route["level"] == "mandatory" else "ЖЕЛАТЕЛЬНО"
        db.add(ClinicalAction(patient_id=patient.id, kind="referral", level=route["level"], title=f"{route['title']}: {mark}",
                              payload={"target": route["target"], "urgency": route["urgency"], "reasons": route["reasons"]},
                              sources=sorted({x["source"] for x in route["reasons"] if x.get("source")})))


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
        "notified": a.notified or [],
    }
