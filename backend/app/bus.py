"""Шина событий реального времени (SSE) для врачей и пациентов.

Синхронные обработчики FastAPI работают в пуле потоков, поэтому публикация идёт
через loop.call_soon_threadsafe. Для горизонтального масштабирования шину
заменяют на Redis Pub/Sub с тем же интерфейсом.
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict


class Bus:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def bind(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.subs[channel].add(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue):
        self.subs[channel].discard(q)

    def listeners(self, channel: str) -> int:
        return len(self.subs.get(channel, ()))

    def publish(self, channel: str, event: str, data: dict) -> int:
        payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
        queues = list(self.subs.get(channel, ()))
        if not queues or self.loop is None:
            return 0
        for q in queues:
            self.loop.call_soon_threadsafe(_put, q, payload)
        return len(queues)


def _put(q: asyncio.Queue, payload: str):
    try:
        q.put_nowait(payload)
    except asyncio.QueueFull:
        pass


bus = Bus()


def doctor_channel(doctor_id: int) -> str:
    return f"doctor:{doctor_id}"


def patient_channel(patient_id: int) -> str:
    return f"patient:{patient_id}"
