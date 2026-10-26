"""Сборка приложения: конфигурация, логирование, схема БД, справочники,
фоновые задачи, middleware (идентификатор запроса, журнал доступа, метрики,
заголовки безопасности, лимит размера тела), единый формат ошибок, роутеры."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from . import errors, jobs, observability
from .api import admin, analytics, doctor, knowledge as knowledge_api, metrics, patient, push, system
from .api import auth as auth_api
from .bus import bus
from .config import APP_ENV, CORS_ORIGINS, DOCS_ENABLED, LOG_DIR, LOG_LEVEL, MAX_BODY_BYTES, production_problems
from .db import IS_SQLITE, Base, engine
from .engine import knowledge
from .models import now

observability.setup_logging(LOG_DIR, LOG_LEVEL)
log = logging.getLogger("kompas")
access = logging.getLogger("kompas.access")


@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = production_problems()
    if problems:
        for p in problems:
            log.critical("небезопасная конфигурация: %s", p)
        raise SystemExit("APP_ENV=production: исправьте конфигурацию (см. лог)")
    # Схема и справочники — один раз, под блокировкой (несколько процессов стартуют одновременно)
    with engine.begin() as conn:
        if not IS_SQLITE:
            conn.exec_driver_sql("SELECT pg_advisory_xact_lock(724001)")
        Base.metadata.create_all(conn)
        # create_all не меняет существующие таблицы: добавить поле повторной проверки TOTP.
        user_columns = {col["name"] for col in inspect(conn).get_columns("users")}
        if "totp_last_step" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN totp_last_step BIGINT")
        for table, column, ddl in (("dose_logs", "reminded_at", "TIMESTAMP"), ("scale_assignments", "reminded_on", "DATE"),
                                   ("patients", "diary_reminded_on", "DATE")):
            if column not in {col["name"] for col in inspect(conn).get_columns(table)}:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        if "analysis" not in {col["name"] for col in inspect(conn).get_columns("adverse_events")}:
            conn.exec_driver_sql("ALTER TABLE adverse_events ADD COLUMN analysis JSON")
        if "resolved_at" not in {col["name"] for col in inspect(conn).get_columns("alerts")}:
            conn.exec_driver_sql("ALTER TABLE alerts ADD COLUMN resolved_at TIMESTAMP")
        if "must_change_password" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE")
        with Session(bind=conn) as db:
            knowledge.seed(db)
            unverified_knowledge = knowledge.unverified_clinical_items(knowledge.get(db))
    if APP_ENV == "production" and unverified_knowledge:
        preview = ", ".join(unverified_knowledge[:12])
        extra = f" (и ещё {len(unverified_knowledge) - 12})" if len(unverified_knowledge) > 12 else ""
        log.critical("clinical knowledge has not been verified: %s%s", preview, extra)
        raise SystemExit(
            "APP_ENV=production: есть непроверенные клинические справочники. "
            "Проверьте их по официальным источникам, измените флаг verified только после рецензии; "
            "для синтетической локальной демонстрации используйте APP_ENV=development."
        )
    await bus.start()
    tasks = jobs.start()
    log.info("started", extra={"event": "startup", "component": f"env={APP_ENV}"})
    yield
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await bus.stop()
    log.info("stopped", extra={"event": "shutdown"})


app = FastAPI(
    title="Компас API", version="1.0", lifespan=lifespan,
    description="Цифровой ассистент врача для ведения пациентов с тревожной и депрессивной симптоматикой. "
                "Ошибки возвращаются в формате Problem Details (RFC 9457) с идентификатором запроса.",
    docs_url="/docs" if DOCS_ENABLED else None, redoc_url=None, openapi_url="/openapi.json" if DOCS_ENABLED else None,
)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"],
                   allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Last-Event-ID"],
                   expose_headers=["X-Request-ID", "X-Total-Count", "Retry-After"])
errors.install(app)

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
async def request_context(request: Request, call_next):
    rid = observability.new_request_id(request.headers.get("x-request-id"))
    token = observability.request_id_var.set(rid)
    uid_token = observability.user_id_var.set(None)
    request.state.received_at = now()  # фиксация момента получения данных
    t0 = time.perf_counter()
    try:
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            response = errors.problem(413, f"Тело запроса больше {MAX_BODY_BYTES // 1024} КБ")
        else:
            try:
                response = await call_next(request)
            except Exception:  # страховка: обработчики ошибок не сработали
                log.exception("unhandled error on %s %s", request.method, request.url.path)
                response = errors.problem(500, "Непредвиденная ошибка. Сообщите в поддержку номер запроса.")
        ms = (time.perf_counter() - t0) * 1000
        route = request.scope.get("route")
        path_tpl = getattr(route, "path", request.url.path)
        streaming = request.url.path.endswith("/stream")
        if request.url.path.startswith("/api") and not streaming:
            metrics.record(f"{request.method} {path_tpl}", ms, response.status_code)
        # журнал доступа: шаблон пути (без идентификаторов и query — в них могут быть данные), статус, время
        level = logging.ERROR if response.status_code >= 500 else logging.WARNING if response.status_code >= 400 else logging.INFO
        access.log(level, "%s %s %s", request.method, path_tpl, response.status_code,
                   extra={"method": request.method, "path": path_tpl, "status": response.status_code, "duration_ms": round(ms, 1)})
        response.headers["X-Request-ID"] = rid
        response.headers["Server-Timing"] = f"app;dur={ms:.1f}"
        for k, v in SECURITY_HEADERS.items():
            if k == "Content-Security-Policy" and request.url.path == "/docs":
                continue  # Swagger UI грузит ресурсы с CDN; в production /docs выключен
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response
    finally:
        observability.request_id_var.reset(token)
        observability.user_id_var.reset(uid_token)


for r in (system.router, auth_api.router, patient.router, doctor.router, knowledge_api.router, admin.router, admin.review,
          analytics.router, metrics.router, push.router):
    app.include_router(r)
