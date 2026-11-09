from datetime import UTC, datetime
from typing import Any, cast

from app.models import AlarmOperator

from ingestor.alarms import Rule, Transition, breached, transition
from ingestor.state import Row
from ingestor.writer import ReadingWriter

HI = Rule(1, 7, AlarmOperator.gt, 1500.0, "critical")
LO = Rule(2, 7, AlarmOperator.lt, 10.0, "warning")


def test_breached_respects_operator() -> None:
    assert breached(HI, 1600) and not breached(HI, 1500)  # strictly greater
    assert breached(LO, 9.9) and not breached(LO, 10)


def test_transitions_are_edge_triggered() -> None:
    assert transition(is_open=False, is_breached=True) is Transition.OPEN
    assert transition(is_open=True, is_breached=True) is None  # still high: no new event
    assert transition(is_open=True, is_breached=False) is Transition.CLEAR
    assert transition(is_open=False, is_breached=False) is None


def test_buffer_is_bounded_and_drops_oldest() -> None:
    w = ReadingWriter(cast(Any, None), max_buffer=3)
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    w.add([Row(1, ts, float(i)) for i in range(5)])
    assert [r.value for r in w.buffer] == [2.0, 3.0, 4.0]  # oldest two fell off
    assert w.dropped == 2
