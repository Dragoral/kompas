from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select

from . import auth
from .api import admin, doctor, metrics, patient
from .api import auth as auth_api
from .bus import bus, doctor_channel
from .config import BASE_DIR, CORS_ORIGINS, ESCALATION_CHECK_SEC
from .crypto import vault
from .db import Base, SessionLocal, engine
from .engine import alerts, knowledge
from .models import Alert, Message, Patient, User, now

log = logging.getLogger("kompas")
RETENTION_MESSAGES_DAYS = 365  # сопутствующие материалы — 1 год (193н п. 51)


def escalate_once() -> int:
    """Критический алерт без подтверждения дольше порога -> дежурному врачу (193н п. 44, 46 «л»)."""
    n = 0
    with SessionLocal() as db:
        t = now()
        pending = db.scalars(select(Alert).where(Alert.status == "new", Alert.escalate_after_min.is_not(None),
                                                 Alert.escalated_to.is_(None))).all()
        for a in pending:
            if a.created_at + timedelta(minutes=a.escalate_after_min) > t:
                continue
            duty = db.scalar(select(User).where(User.is_duty.is_(True), User.active.is_(True), User.id != a.doctor_id))
            if not duty:
                continue
            a.escalated_to, a.escalated_at = duty.id, t
            auth.audit(db, None, "alert_escalated", "alert", a.id, patient_id=a.patient_id, to_user=duty.id)
            db.commit()
            bus.publish(doctor_channel(duty.id), "alert", {**alerts.alert_dict(a, db.get(Patient, a.patient_id)), "escalated": True})
            n += 1
    return n


def maintenance_once() -> None:
    auth.seal_audit()
    with SessionLocal() as db:
        t = now()
        db.execute(delete(Message).where(Message.created_at < t - timedelta(days=RETENTION_MESSAGES_DAYS)))
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
        with open(BASE_DIR / "data" / "audit_anchor.log", "a", encoding="utf-8") as f:
            f.write(f"{now().isoformat()} {head}\n")


async def _loop(fn, period: float):
    while True:
        try:
            await asyncio.to_thread(fn)
        except Exception:
            log.exception("background task %s failed", fn.__name__)
        await asyncio.sleep(period)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        knowledge.seed(db)
    bus.bind(asyncio.get_running_loop())
    tasks = [asyncio.create_task(_loop(escalate_once, ESCALATION_CHECK_SEC)),
             asyncio.create_task(_loop(maintenance_once, 60))]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Компас API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


@app.middleware("http")
async def envelope(request: Request, call_next):
    request.state.received_at = now()  # фиксация момента получения данных
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error on %s", request.url.path)  # без тела запроса — в нём могут быть ПДн
        response = JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500)
    ms = (time.perf_counter() - t0) * 1000
    route = request.scope.get("route")
    if request.url.path.startswith("/api") and not request.url.path.endswith("/stream"):
        metrics.record(f"{request.method} {getattr(route, 'path', request.url.path)}", ms, response.status_code)
    response.headers["Server-Timing"] = f"app;dur={ms:.1f}"
    for k, v in SECURITY_HEADERS.items():
        if k == "Content-Security-Policy" and request.url.path in ("/docs", "/redoc"):
            continue  # Swagger UI грузит ресурсы с CDN; в production /docs отключается
        response.headers.setdefault(k, v)
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


for r in (auth_api.router, patient.router, doctor.router, admin.router, metrics.router):
    app.include_router(r)
