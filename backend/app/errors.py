"""Единый формат ошибок API — Problem Details (RFC 9457, application/problem+json).

Любая ошибка возвращается одинаково:
    {"type": "...", "title": "...", "status": 422, "detail": "...",
     "request_id": "...", "errors": [{"field": "body.answers.9", "message": "..."}]}
* title/detail — по-русски, понятно пользователю;
* errors — построчно по полям (для форм в интерфейсе);
* request_id — для обращения в поддержку (по нему находится запись в логах).
Внутренние детали (трассировка, SQL) клиенту не отдаются — только в лог.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

from .observability import request_id_var

log = logging.getLogger("kompas.errors")
MEDIA = "application/problem+json"

TITLES = {400: "Некорректный запрос", 401: "Требуется вход", 403: "Нет доступа", 404: "Не найдено",
          405: "Метод не поддерживается", 409: "Конфликт", 413: "Слишком большой запрос", 422: "Ошибка в данных",
          429: "Слишком много попыток", 500: "Внутренняя ошибка", 503: "Сервис временно недоступен"}

# Сообщения валидации pydantic -> по-русски
_MSG = {
    "missing": "Обязательное поле",
    "int_parsing": "Ожидается целое число", "int_type": "Ожидается целое число",
    "float_parsing": "Ожидается число", "float_type": "Ожидается число",
    "bool_parsing": "Ожидается да/нет", "bool_type": "Ожидается да/нет",
    "string_type": "Ожидается строка", "date_from_datetime_parsing": "Ожидается дата ГГГГ-ММ-ДД",
    "date_parsing": "Ожидается дата ГГГГ-ММ-ДД", "datetime_parsing": "Ожидается дата и время (ISO 8601)",
    "dict_type": "Ожидается объект", "list_type": "Ожидается список", "json_invalid": "Некорректный JSON",
    "string_pattern_mismatch": "Значение не соответствует формату",
    "extra_forbidden": "Неизвестное поле",
}


def _validation_message(e: dict) -> str:
    t, ctx = e.get("type", ""), e.get("ctx") or {}
    if t in _MSG:
        return _MSG[t]
    if t == "string_too_short":
        return f"Не короче {ctx.get('min_length')} символов"
    if t == "string_too_long":
        return f"Не длиннее {ctx.get('max_length')} символов"
    if t in ("greater_than_equal", "greater_than"):
        return f"Значение должно быть не меньше {ctx.get('ge', ctx.get('gt'))}"
    if t in ("less_than_equal", "less_than"):
        return f"Значение должно быть не больше {ctx.get('le', ctx.get('lt'))}"
    if t == "too_long":
        return f"Не больше {ctx.get('max_length')} элементов"
    if t == "value_error":
        return str(ctx.get("error", e.get("msg", "Некорректное значение")))
    return "Некорректное значение"


def problem(status: int, detail: str | None = None, *, title: str | None = None, errors: list | None = None,
            type_: str | None = None, headers: dict | None = None, extra: dict | None = None) -> JSONResponse:
    body = {"type": type_ or f"https://kompas/errors/{status}", "title": title or TITLES.get(status, "Ошибка"),
            "status": status, "detail": detail or title or TITLES.get(status, "Ошибка"), "request_id": request_id_var.get()}
    if errors:
        body["errors"] = errors
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=MEDIA, headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        d = exc.detail
        if isinstance(d, dict):  # подробности (например, оценка препарата при отказе в назначении)
            msg = d.get("message") or d.get("detail") or TITLES.get(exc.status_code)
            return problem(exc.status_code, msg, headers=getattr(exc, "headers", None),
                           extra={k: v for k, v in d.items() if k not in ("message", "detail")})
        return problem(exc.status_code, str(d), headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [{"field": ".".join(str(x) for x in e.get("loc", [])), "message": _validation_message(e)} for e in exc.errors()]
        return problem(422, "Проверьте введённые данные", errors=errors)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError):
        log.warning("integrity error on %s: %s", request.url.path, exc.orig.__class__.__name__)
        return problem(409, "Запись конфликтует с существующими данными (возможно, дубликат)")

    @app.exception_handler(OperationalError)
    async def db_operational(request: Request, exc: OperationalError):
        text = str(exc)
        if "locked" in text or "too many clients" in text or "timed out" in text.lower():
            log.warning("db backpressure on %s", request.url.path)
            # клиент повторит запрос; офлайн-очередь пациента досылает без дублей (client_id)
            return problem(503, "Сервер перегружен, повторите запрос через несколько секунд", headers={"Retry-After": "2"})
        log.exception("database error on %s", request.url.path)
        return problem(503, "База данных временно недоступна", headers={"Retry-After": "5"})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # без тела запроса — в нём могут быть персональные данные
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return problem(500, "Непредвиденная ошибка. Сообщите в поддержку номер запроса.")
