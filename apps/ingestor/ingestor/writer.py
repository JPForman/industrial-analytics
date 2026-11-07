"""Buffered, idempotent bulk writer with bounded memory, plus alarm evaluation per flush."""

import logging
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.models import AlarmEvent, Reading
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ingestor.alarms import Rule, Transition, breached, transition
from ingestor.state import Row

log = logging.getLogger("ingestor.writer")

AlarmPublisher = Callable[[dict[str, object]], Awaitable[None]]


class ReadingWriter:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        max_buffer: int = 50_000,
        publish_alarm: AlarmPublisher | None = None,
    ) -> None:
        self.sessions = sessions
        # deque(maxlen) = bounded buffer: when full, the OLDEST rows fall off. If the DB is down
        # for a long time we lose the oldest data instead of running out of memory and losing all.
        self.buffer: deque[Row] = deque(maxlen=max_buffer)
        self.dropped = 0
        self.rules: dict[int, list[Rule]] = {}
        self.open_events: dict[int, int] = {}  # rule_id -> event id
        self.publish_alarm = publish_alarm

    def add(self, rows: list[Row]) -> None:
        overflow = len(self.buffer) + len(rows) - (self.buffer.maxlen or 0)
        if overflow > 0:
            self.dropped += overflow
            log.warning(
                "buffer full: dropping %d oldest rows (total dropped %d)", overflow, self.dropped
            )
        self.buffer.extend(rows)

    def __len__(self) -> int:
        return len(self.buffer)

    async def flush(self, max_rows: int = 5000) -> int:
        """Write up to `max_rows`. On failure the rows stay buffered for the next attempt."""
        if not self.buffer:
            return 0
        batch = [self.buffer[i] for i in range(min(max_rows, len(self.buffer)))]
        # Alarm state is mutated during evaluation; if the transaction fails, the DB rolls back,
        # so memory must roll back too or a retry would skip (or duplicate) alarm events.
        open_before = dict(self.open_events)
        try:
            async with self.sessions() as session:
                await session.execute(
                    insert(Reading)
                    .values([{"tag_id": r.tag_id, "ts": r.ts, "value": r.value} for r in batch])
                    .on_conflict_do_nothing(index_elements=["tag_id", "ts"])
                )
                events = await self._evaluate_alarms(session, batch)
                await session.commit()
        except Exception:
            self.open_events = open_before
            raise
        for _ in batch:  # only remove once the commit succeeded
            self.buffer.popleft()
        for event in events:
            if self.publish_alarm:
                await self.publish_alarm(event)
        return len(batch)

    async def _evaluate_alarms(
        self, session: AsyncSession, batch: list[Row]
    ) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for row in sorted(batch, key=lambda r: r.ts):
            for rule in self.rules.get(row.tag_id, []):
                change = transition(rule.id in self.open_events, breached(rule, row.value))
                if change is Transition.OPEN:
                    event = AlarmEvent(rule_id=rule.id, triggered_at=row.ts, value=row.value)
                    session.add(event)
                    await session.flush()  # assigns event.id
                    self.open_events[rule.id] = event.id
                elif change is Transition.CLEAR:
                    event_id = self.open_events.pop(rule.id)
                    await session.execute(
                        update(AlarmEvent)
                        .where(AlarmEvent.id == event_id)
                        .values(cleared_at=row.ts)
                    )
                else:
                    continue
                events.append(
                    {
                        "kind": change.value,
                        "rule_id": rule.id,
                        "tag_id": row.tag_id,
                        "severity": rule.severity,
                        "value": row.value,
                        "ts": row.ts.astimezone(UTC).isoformat(),
                        "at": datetime.now(UTC).isoformat(),
                    }
                )
        return events
