# src/lib/events.py
import time
import json
from collections import deque
from typing import Any, Callable

class EventBus:
    """Sync pub/sub. Agents call bus.emit(); subscribers (terminal, web) react."""
    def __init__(self, max_history: int = 1000):
        self.subscribers: list[Callable[[dict], None]] = []
        self.history: deque[dict] = deque(maxlen=max_history)
        self._enabled = True

    def emit(self, ticket_id: str, kind: str, message: str, **meta) -> None:
        if not self._enabled:
            return
        event = {
            "ts": time.time(),
            "ticket_id": ticket_id,
            "kind": kind,       # picked|due|moved|opened|typed|pr|review|done|error
            "message": message,
            "meta": meta,
        }
        self.history.append(event)
        for cb in list(self.subscribers):
            try:
                cb(event)
            except Exception as e:
                print(f"[events] subscriber failed: {e}")

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        self.subscribers.append(callback)

    def snapshot(self) -> list[dict]:
        return list(self.history)

    def disable(self):  self._enabled = False
    def enable(self):   self._enabled = True


# Singleton
bus = EventBus()