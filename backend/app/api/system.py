"""Состояние системы.

/api/health — процесс жив (для оркестратора/балансировщика, без БД).
/api/ready  — готов принимать запросы: БД, справочники, доставка событий,
              фоновые задачи. 503 + список причин, если что-то не так.
/api/admin/system — сводка для администратора: компоненты, проблемы,
              очереди, уведомления, черновики справочников, бэкапы, конфигурация.
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import auth, errors, observability
from ..bus import bus
from ..config import APP_ENV, BASE_DIR, DATABASE_URL, DOCS_ENABLED
from ..db import IS_SQLITE, get_db
from ..engine import knowledge
from ..jobs import SCHEDULE
from ..models import Event, KnowledgeVersion, Notification, User, now

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health():
    return {"status": "ok", "uptime_s": round(time.time() - observability.STARTED_AT)}


def _checks(db: Session) -> dict:
    checks: dict[str, dict] = {}
    t0 = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:
        checks["database"] = {"ok": False, "error": e.__class__.__name__}
        return checks
    kb = knowledge.get(db)
    n = sum(len(kb.get(k, {})) for k in ("scale", "drug", "rules", "guideline"))
    checks["knowledge"] = {"ok": n > 0 and "alerts" in kb["rules"] and "routing" in kb["rules"], "items": n}
    checks["event_dispatch"] = {"ok": bus._task is not None and not bus._task.done()}
    comps = observability.components()
    now_s = time.time()
    for name, (_, period) in SCHEDULE.items():
        c = comps.get(name)
        if not c:  # задачу выполняет другой процесс (аренда) или она ещё не запускалась
            checks[f"job:{name}"] = {"ok": True, "note": "нет запусков в этом процессе"}
            continue
        stale = c.get("last_success") is None or now_s - c["last_success"] > max(period * 3, 180)
        checks[f"job:{name}"] = {"ok": c["consecutive_failures"] < 3 and not stale,
                                 "consecutive_failures": c["consecutive_failures"], "last_error": c.get("last_error")}
    return checks


@router.get("/api/ready")
def ready(db: Session = Depends(get_db)):
    """Публичный readiness probe без раскрытия внутренней диагностики.

    Подробности проверок, ошибки фоновых задач и сведения о компонентах доступны
    только через защищённый /api/admin/system.
    """
    checks = _checks(db)
    ok = all(c.get("ok") for c in checks.values())
    if not ok:
        # Не передавать имена внутренних компонентов и тексты ошибок наружу.
        # Оркестратору достаточно HTTP 503, администратор увидит детали в system.
        return errors.problem(503, "Сервис временно не готов")
    return {"status": "ready"}


@router.get("/api/admin/system")
def system_status(user: User = Depends(auth.require("admin")), db: Session = Depends(get_db)):
    checks = _checks(db)
    t = now()
    drill = BASE_DIR / "data" / "backup_drill.json"
    backups = sorted((BASE_DIR / "data" / "backups").glob("kompas-*.db.enc")) if IS_SQLITE else []
    return {
        "environment": APP_ENV, "database": "sqlite" if IS_SQLITE else DATABASE_URL.split("://")[0],
        "docs_enabled": DOCS_ENABLED, "uptime_s": round(time.time() - observability.STARTED_AT),
        "checks": checks,
        "components": observability.components(),
        "problems": observability.problems(50),
        "queues": {
            "events_backlog": db.scalar(select(func.count()).select_from(Event).where(Event.id > bus.last_id)),
            "notifications_pending": db.scalar(select(func.count()).select_from(Notification).where(Notification.status == "pending")),
            "notifications_failed": db.scalar(select(func.count()).select_from(Notification).where(Notification.status == "failed")),
        },
        "knowledge_drafts_pending": db.scalar(select(func.count()).select_from(KnowledgeVersion).where(KnowledgeVersion.status == "draft")),
        "backups": {"count": len(backups), "latest": backups[-1].name if backups else None,
                    "last_drill": json.loads(drill.read_text(encoding="utf-8")) if drill.exists() else None},
        "checked_at": t,
    }
