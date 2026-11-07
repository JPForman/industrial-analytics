"""Integration tests against real Postgres: registration, dedup, alarm lifecycle, failure."""

from datetime import UTC, datetime, timedelta

import pytest
from app.models import AlarmEvent, AlarmOperator, AlarmRule, Reading, Severity, Tag
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ingestor.alarms import load_open_events, load_rules
from ingestor.registry import upsert_device
from ingestor.state import BirthMetric, DeviceBirth, Row
from ingestor.writer import ReadingWriter
from tests.conftest import needs_postgres

pytestmark = needs_postgres

Sessions = async_sessionmaker[AsyncSession]
T0 = datetime(2026, 1, 1, tzinfo=UTC)
BIRTH = DeviceBirth(
    "laser", [BirthMetric("power_w", 100, "W"), BirthMetric("head_temp_c", 101, "degC")]
)


async def register(sessions: Sessions) -> dict[int, int]:
    async with sessions() as s:
        return await upsert_device(s, "edge1", "laser1", BIRTH)


async def count(sessions: Sessions, model: type[Reading] | type[AlarmEvent]) -> int:
    async with sessions() as s:
        return await s.scalar(select(func.count()).select_from(model)) or 0


async def test_registration_is_idempotent_and_updates_units(sessions: Sessions) -> None:
    first = await register(sessions)
    assert set(first) == {100, 101}
    rebirth = DeviceBirth(
        "laser", [BirthMetric("power_w", 100, "kW"), BirthMetric("head_temp_c", 101, "degC")]
    )
    async with sessions() as s:
        second = await upsert_device(s, "edge1", "laser1", rebirth)
    assert second == first  # same tag ids after a rebirth
    async with sessions() as s:
        assert await s.scalar(select(Tag.unit).where(Tag.id == first[100])) == "kW"


async def test_flush_is_idempotent(sessions: Sessions) -> None:
    tag = (await register(sessions))[100]
    w = ReadingWriter(sessions)
    rows = [Row(tag, T0 + timedelta(seconds=i), 1000.0) for i in range(10)]
    w.add(rows)
    w.add(rows)  # redelivered duplicates
    assert await w.flush() == 20
    assert await count(sessions, Reading) == 10 and len(w) == 0


async def make_rule(sessions: Sessions, tag_id: int) -> None:
    async with sessions() as s:
        s.add(
            AlarmRule(
                tag_id=tag_id, operator=AlarmOperator.gt, threshold=1500, severity=Severity.critical
            )
        )
        await s.commit()


async def test_alarm_opens_once_and_clears(sessions: Sessions) -> None:
    tag = (await register(sessions))[100]
    await make_rule(sessions, tag)
    published: list[dict[str, object]] = []

    async def capture(event: dict[str, object]) -> None:
        published.append(event)

    w = ReadingWriter(sessions, publish_alarm=capture)
    async with sessions() as s:
        w.rules = await load_rules(s)
    values = [1000, 1600, 1700, 1650, 1000, 1000]  # one excursion lasting three readings
    w.add([Row(tag, T0 + timedelta(seconds=i), float(v)) for i, v in enumerate(values)])
    await w.flush()
    async with sessions() as s:
        (event,) = (await s.scalars(select(AlarmEvent))).all()  # exactly ONE event
    assert event.value == 1600 and event.cleared_at is not None
    assert event.cleared_at - event.triggered_at == timedelta(seconds=3)
    assert [e["kind"] for e in published] == ["open", "clear"]


async def test_open_alarm_survives_restart_without_duplicate(sessions: Sessions) -> None:
    tag = (await register(sessions))[100]
    await make_rule(sessions, tag)
    w = ReadingWriter(sessions)
    async with sessions() as s:
        w.rules = await load_rules(s)
    w.add([Row(tag, T0, 1600.0)])
    await w.flush()
    restarted = ReadingWriter(sessions)  # new process: state comes from the DB
    async with sessions() as s:
        restarted.rules = await load_rules(s)
        restarted.open_events = await load_open_events(s)
    restarted.add([Row(tag, T0 + timedelta(seconds=1), 1700.0)])  # still high
    await restarted.flush()
    assert await count(sessions, AlarmEvent) == 1


async def test_failed_flush_keeps_rows_and_alarm_state(sessions: Sessions) -> None:
    tag = (await register(sessions))[100]
    await make_rule(sessions, tag)
    w = ReadingWriter(sessions)
    async with sessions() as s:
        w.rules = await load_rules(s)
    w.add([Row(tag, T0, 1600.0)])

    failed = False

    def flaky() -> AsyncSession:
        nonlocal failed
        session = sessions()
        if not failed:
            failed = True

            async def db_down() -> None:
                raise ConnectionError("db down")

            session.commit = db_down  # type: ignore[method-assign]
        return session

    w.sessions = flaky  # type: ignore[assignment]
    with pytest.raises(ConnectionError):
        await w.flush()
    assert len(w) == 1 and w.open_events == {}  # nothing lost, no phantom open alarm
    await w.flush()  # DB back
    assert await count(sessions, AlarmEvent) == 1 and await count(sessions, Reading) == 1
