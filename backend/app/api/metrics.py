from __future__ import annotations

import json
import statistics
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import auth
from ..bus import bus
from ..config import BASE_DIR
from ..db import get_db
from ..engine import context, knowledge, recommend
from ..models import Alert, Patient, User

router = APIRouter(prefix="/api", tags=["metrics"])

_lock = threading.Lock()
_latency: dict[str, deque] = defaultdict(lambda: deque(maxlen=2000))
_errors = {"5xx": 0, "4xx": 0, "total": 0}
STARTED = time.time()


def record(route: str, ms: float, status: int) -> None:
    with _lock:
        _latency[route].append(ms)
        _errors["total"] += 1
        if status >= 500:
            _errors["5xx"] += 1
        elif status >= 400:
            _errors["4xx"] += 1


def _pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * q))], 1)


@router.get("/metrics")
def metrics(user: User = Depends(auth.require("doctor", "admin")), db: Session = Depends(get_db)):
    with _lock:
        routes = {r: {"n": len(v), "p50_ms": _pct(v, .5), "p95_ms": _pct(v, .95), "max_ms": round(max(v), 1)}
                  for r, v in _latency.items() if v}
        errors = dict(_errors)
    rows = db.scalars(select(Alert).where(Alert.pushed_at.is_not(None)).order_by(Alert.id.desc()).limit(500)).all()
    push = [(a.pushed_at - a.data_received_at).total_seconds() * 1000 for a in rows]
    deliver = [(a.delivered_at - a.data_received_at).total_seconds() * 1000 for a in rows if a.delivered_at]
    ack = [(a.acknowledged_at - a.created_at).total_seconds() for a in rows if a.acknowledged_at]

    # время формирования рекомендаций — живой замер по пациентам врача
    rec_ms = []
    kb = knowledge.get(db)
    for p in db.scalars(select(Patient).where(Patient.erased_at.is_(None)).limit(20)):
        t0 = time.perf_counter()
        recommend.recommend(context.build(db, p), kb)
        rec_ms.append((time.perf_counter() - t0) * 1000)

    eval_path = BASE_DIR / "data" / "extraction_eval.json"
    drill_path = BASE_DIR / "data" / "backup_drill.json"
    return {
        "requests": routes,
        "errors": errors,
        "alerts": {
            "server_ms_p50": _pct(push, .5), "server_ms_p95": _pct(push, .95),
            "delivery_ms_p50": _pct(deliver, .5), "delivery_ms_p95": _pct(deliver, .95),
            "ack_s_median": round(statistics.median(ack), 1) if ack else None, "n": len(rows),
        },
        "recommendations_ms": {"p50": _pct(rec_ms, .5), "p95": _pct(rec_ms, .95), "n": len(rec_ms)},
        "extraction": json.loads(eval_path.read_text(encoding="utf-8")) if eval_path.exists() else None,
        "backup_drill": json.loads(drill_path.read_text(encoding="utf-8")) if drill_path.exists() else None,
        "realtime_listeners": sum(len(v) for v in bus.subs.values()),
        "db": {"patients": db.scalar(select(func.count()).select_from(Patient))},
    }
