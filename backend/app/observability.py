"""Наблюдаемость: структурированные логи, сквозной идентификатор запроса,
состояние компонентов и журнал проблем для администратора.

* Логи — JSON по строке (stdout + файл с ротацией), с request_id, без ПДн:
  в лог никогда не пишутся тела запросов, тексты пациентов, ФИО.
* request_id — из заголовка X-Request-ID (если корректен) или новый UUID;
  возвращается клиенту в заголовке и в теле ошибки — по нему поддержка
  находит запись в логах.
* Реестр компонентов: фоновые задачи отмечают каждый запуск (успех/ошибка,
  длительность); /api/ready и /api/admin/system показывают их состояние.
* Журнал проблем: сбой правила, справочника, провайдера уведомлений не роняет
  запрос, а фиксируется здесь и виден администратору.
"""
from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import os
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
user_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar("user_id", default=None)
_RID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def new_request_id(incoming: str | None) -> str:
    return incoming if incoming and _RID.match(incoming) else uuid.uuid4().hex


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        d = {
            "ts": datetime.fromtimestamp(r.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": r.levelname, "logger": r.name, "msg": r.getMessage(),
            "request_id": request_id_var.get(),
        }
        uid = user_id_var.get()
        if uid is not None:
            d["user_id"] = uid
        for k in ("method", "path", "status", "duration_ms", "component", "event"):
            if hasattr(r, k):
                d[k] = getattr(r, k)
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d, ensure_ascii=False)


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_kompas_configured", False):
        return
    fmt = JsonFormatter()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(log_dir / "kompas.log", maxBytes=20_000_000, backupCount=10, encoding="utf-8"))
    except OSError:
        pass  # только stdout (например, файловая система только для чтения)
    for h in handlers:
        h.setFormatter(fmt)
    root.handlers = handlers
    root.setLevel(level)
    # access-лог uvicorn заменён нашим (с request_id и без query-параметров)
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    root._kompas_configured = True


# --- состояние компонентов -------------------------------------------------------
_lock = threading.Lock()
_components: dict[str, dict] = {}
_problems: deque = deque(maxlen=500)
STARTED_AT = time.time()


def task_ran(name: str, ok: bool, duration_ms: float, error: str | None = None) -> None:
    with _lock:
        c = _components.setdefault(name, {"runs": 0, "failures": 0, "consecutive_failures": 0})
        c["runs"] += 1
        c["last_run"] = time.time()
        c["last_duration_ms"] = round(duration_ms, 1)
        if ok:
            c["last_success"] = c["last_run"]
            c["consecutive_failures"] = 0
        else:
            c["failures"] += 1
            c["consecutive_failures"] += 1
            c["last_error"] = (error or "")[:300]


def components() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _components.items()}


def report_problem(component: str, ref: str, error: str, level: str = "error") -> None:
    """Сбой, который не должен ронять запрос (правило, справочник, провайдер)."""
    entry = {"ts": time.time(), "component": component, "ref": ref, "error": error[:500], "level": level,
             "request_id": request_id_var.get()}
    with _lock:
        _problems.append(entry)
    logging.getLogger("kompas.problems").log(logging.ERROR if level == "error" else logging.WARNING,
                                             "%s %s: %s", component, ref, error[:500], extra={"component": component})


def problems(limit: int = 100) -> list[dict]:
    with _lock:
        return list(_problems)[-limit:][::-1]
