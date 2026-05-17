"""In-process async pub/sub bus for realtime dashboard pushes.

Producers (ingest, alerts, scheduler) call `publish_sync(...)` from sync code
or `await publish(...)` from async code. WebSocket consumers `subscribe()` and
read from an asyncio.Queue.
"""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Optional


@dataclass
class Event:
    type: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }, default=str)


class EventBus:
    def __init__(self, max_queue: int = 1000) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._max_queue = max_queue

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    async def publish(self, evt: Event) -> None:
        with self._lock:
            queues = list(self._subscribers)
        for q in queues:
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await q.put(evt)

    def publish_sync(self, evt: Event) -> None:
        """Safe-to-call from sync code (ingest, scheduler)."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self.publish(evt), loop)

    async def stream(self, q: asyncio.Queue[Event]) -> AsyncIterator[Event]:
        try:
            while True:
                evt = await q.get()
                yield evt
        finally:
            self.unsubscribe(q)


bus = EventBus()
