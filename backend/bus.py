"""In-process event bus + WebSocket hub.

Every phase publishes through here: ingestion pushes signals, the simulator
pushes cascade stages, agents push trace steps. The frontend subscribes once
and renders whatever arrives. Keeping this in one place is what makes the
"stopwatch" honest -- we timestamp events at the moment they are published,
not when the UI happens to draw them.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from typing import Any, Deque

from fastapi import WebSocket

from backend.config import Provenance


class EventBus:
    def __init__(self, history: int = 400) -> None:
        self._clients: set[WebSocket] = set()
        self._history: Deque[dict[str, Any]] = deque(maxlen=history)
        self._lock = asyncio.Lock()

    # -- client management ------------------------------------------------
    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        # Replay recent history so a late-joining client is not blind.
        for evt in list(self._history)[-60:]:
            try:
                await ws.send_json(evt)
            except Exception:
                break

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    # -- publishing -------------------------------------------------------
    async def publish(
        self,
        topic: str,
        payload: Any,
        provenance: str = Provenance.SIMULATED,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        evt = {
            "id": uuid.uuid4().hex[:12],
            "topic": topic,
            "ts": time.time(),
            "provenance": provenance,
            "run_id": run_id,
            "payload": payload,
        }
        self._history.append(evt)
        async with self._lock:
            targets = list(self._clients)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(evt)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)
        return evt

    def publish_soon(self, topic: str, payload: Any, **kw: Any) -> None:
        """Fire-and-forget publish from sync code inside a running loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.publish(topic, payload, **kw))

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def recent(self, n: int = 100) -> list[dict[str, Any]]:
        return list(self._history)[-n:]


bus = EventBus()
