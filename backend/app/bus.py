"""Доставка событий в реальном времени (алерты, сообщения, кризисный экран).

Transactional outbox: событие записывается в таблицу events в той же транзакции,
что и данные, которые его вызвали, — алерт не может «потеряться» или уйти раньше
сохранения данных. Каждый рабочий процесс опрашивает таблицу (≈50 мс) и
раздаёт новые события своим SSE-подписчикам. Поэтому:
  * несколько рабочих процессов / серверов (горизонтальное масштабирование);
  * переподключение клиента с Last-Event-ID — пропущенные события досылаются
    (резервная очередь доставки: обрыв связи у врача не теряет алерт);
  * перезапуск сервера не теряет недоставленные события.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

log = logging.getLogger("kompas.bus")
POLL_SEC = 0.05
REPLAY_WINDOW = timedelta(hours=24)


def doctor_channel(doctor_id: int) -> str:
    return f"doctor:{doctor_id}"


def patient_channel(patient_id: int) -> str:
    return f"patient:{patient_id}"


def enqueue(db: Session, channel: str, event: str, data: dict) -> None:
    """Поставить событие в очередь в рамках текущей транзакции."""
    from .models import Event
    db.add(Event(channel=channel, event=event, data=json.loads(json.dumps(data, ensure_ascii=False, default=str))))


def _format(ev_id: int, event: str, data: dict) -> str:
    return f"id: {ev_id}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


class Dispatcher:
    def __init__(self):
        self.subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self.last_id = 0
        self._task: asyncio.Task | None = None

    async def start(self):
        from .db import SessionLocal
        from .models import Event

        def head():
            with SessionLocal() as db:
                return db.scalar(select(func.max(Event.id))) or 0
        self.last_id = await asyncio.to_thread(head)
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()

    def _fetch(self) -> list[tuple[int, str, str, dict]]:
        from .db import SessionLocal
        from .models import Event
        with SessionLocal() as db:
            rows = db.execute(select(Event.id, Event.channel, Event.event, Event.data)
                              .where(Event.id > self.last_id).order_by(Event.id).limit(1000)).all()
        return [tuple(r) for r in rows]

    async def _run(self):
        while True:
            try:
                if self.subs:
                    rows = await asyncio.to_thread(self._fetch)
                    for ev_id, channel, event, data in rows:
                        self.last_id = ev_id
                        for q in list(self.subs.get(channel, ())):
                            if not q.full():
                                q.put_nowait(_format(ev_id, event, data))
                else:
                    self.last_id = await asyncio.to_thread(self._head)
            except Exception:
                log.exception("event dispatch failed")
            await asyncio.sleep(POLL_SEC)

    def _head(self) -> int:
        from .db import SessionLocal
        from .models import Event
        with SessionLocal() as db:
            return db.scalar(select(func.max(Event.id))) or self.last_id

    def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.subs[channel].add(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue):
        self.subs[channel].discard(q)
        if not self.subs[channel]:
            self.subs.pop(channel, None)

    def replay(self, channel: str, after_id: int) -> list[str]:
        """События канала после after_id (за последние 24 ч) — для переподключения."""
        from .db import SessionLocal
        from .models import Event, now
        with SessionLocal() as db:
            rows = db.execute(select(Event.id, Event.event, Event.data).where(
                Event.channel == channel, Event.id > after_id, Event.id <= self.last_id,
                Event.created_at >= now() - REPLAY_WINDOW).order_by(Event.id).limit(500)).all()
        return [_format(i, e, d) for i, e, d in rows]


bus = Dispatcher()
