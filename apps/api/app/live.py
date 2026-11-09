"""In-process fan-out from one MQTT bridge to many WebSocket clients.

Each client gets its own bounded queue. `publish` never awaits, so a slow or stuck browser can
only fill its own queue; it can never stall the bridge or the other clients. When a queue is
full we drop that client's OLDEST message: for a live chart the newest value matters most, and
the dashboard can backfill history over REST.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

Event = dict[str, Any]

DEFAULT_QUEUE_SIZE = 1000


@dataclass(eq=False)  # identity equality, so subscribers can live in a set
class Subscriber:
    tag_ids: frozenset[int] | None = None  # None = every tag
    queue: asyncio.Queue[Event] = field(
        default_factory=lambda: asyncio.Queue(maxsize=DEFAULT_QUEUE_SIZE)
    )
    dropped: int = 0

    def wants(self, event: Event) -> bool:
        if event["type"] != "reading" or self.tag_ids is None:
            return True  # alarms go to everyone
        return event["tag_id"] in self.tag_ids

    def offer(self, event: Event) -> None:
        if self.queue.full():
            self.queue.get_nowait()  # drop oldest; safe, publish is the only producer
            self.dropped += 1
        self.queue.put_nowait(event)


class Broadcaster:
    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self.queue_size = queue_size
        self.subscribers: set[Subscriber] = set()

    @contextmanager
    def subscribe(self, tag_ids: frozenset[int] | None = None) -> Iterator[Subscriber]:
        """Register for the duration of a `with` block, so a disconnect always unregisters."""
        sub = Subscriber(tag_ids, asyncio.Queue(maxsize=self.queue_size))
        self.subscribers.add(sub)
        try:
            yield sub
        finally:
            self.subscribers.discard(sub)

    def publish(self, event: Event) -> None:
        for sub in self.subscribers:
            if sub.wants(event):
                sub.offer(event)


broadcaster = Broadcaster()


def get_broadcaster() -> Broadcaster:
    """Dependency, so tests can swap in a fresh instance."""
    return broadcaster
