import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from httpx import AsyncClient
from httpx_ws import AsyncWebSocketSession, WebSocketDisconnect, aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db import get_db
from app.live import Broadcaster, get_broadcaster
from app.main import app
from app.models import Role
from app.mqtt_bridge import to_event

READING = {"type": "reading", "tag_id": 1, "ts": "2026-11-07T12:00:00+00:00", "value": 1.5}
ALARM = {"type": "alarm", "event": "triggered", "rule_id": 1}

# --- Broadcaster (pure, no network) ---


def reading(tag_id: int, value: float = 0.0) -> dict[str, object]:
    return {**READING, "tag_id": tag_id, "value": value}


async def test_fan_out_to_every_subscriber() -> None:
    b = Broadcaster()
    with b.subscribe() as one, b.subscribe() as two:
        b.publish(READING)
        assert one.queue.get_nowait() == READING
        assert two.queue.get_nowait() == READING


async def test_tag_filter_but_alarms_reach_everyone() -> None:
    b = Broadcaster()
    with b.subscribe(frozenset({2})) as sub:
        b.publish(reading(1))
        b.publish(reading(2))
        b.publish(ALARM)
        assert sub.queue.get_nowait()["tag_id"] == 2
        assert sub.queue.get_nowait() == ALARM
        assert sub.queue.empty()


async def test_full_queue_drops_oldest_without_affecting_others() -> None:
    b = Broadcaster(queue_size=2)
    with b.subscribe() as slow, b.subscribe() as fast:
        for i in range(3):
            b.publish(reading(1, float(i)))
            fast.queue.get_nowait()  # this client keeps up
        assert slow.dropped == 1
        assert [slow.queue.get_nowait()["value"] for _ in range(2)] == [1.0, 2.0]
        assert fast.dropped == 0


async def test_leaving_the_block_unsubscribes() -> None:
    b = Broadcaster()
    with b.subscribe():
        assert len(b.subscribers) == 1
    assert not b.subscribers


# --- MQTT message translation ---


def test_to_event_reading_and_alarm() -> None:
    body = b'{"tag_id": 1, "ts": "2026-11-07T12:00:00+00:00", "value": 1.5}'
    assert to_event("ia/v1/live/1", body) == READING
    assert to_event("ia/v1/alarms", b'{"event": "triggered", "rule_id": 1}') == ALARM


@pytest.mark.parametrize(
    ("topic", "body"),
    [
        ("ia/v1/live/1", b"not json"),
        ("ia/v1/live/1", b"[1, 2]"),
        ("ia/v1/live/1", b'{"tag_id": 1}'),
        ("somewhere/else", b'{"tag_id": 1, "ts": "x", "value": 1}'),
    ],
)
def test_to_event_rejects_malformed(topic: str, body: bytes) -> None:
    assert to_event(topic, body) is None


# --- WebSocket endpoint ---


@pytest.fixture
async def live(db_session: AsyncSession) -> AsyncIterator[Broadcaster]:
    """Overrides only. The client is opened inside each test: httpx-ws runs an anyio task group
    that must be entered and exited in the same task, which a yield fixture can't guarantee."""

    async def override_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    b = Broadcaster()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_broadcaster] = lambda: b
    yield b
    app.dependency_overrides.clear()


def ws_client() -> AsyncClient:
    return AsyncClient(transport=ASGIWebSocketTransport(app=app), base_url="http://test")


async def token_for(auth_headers: Callable[[Role], Awaitable[dict[str, str]]]) -> str:
    return (await auth_headers(Role.viewer))["Authorization"].removeprefix("Bearer ")


async def rejection_code(url: str) -> int | None:
    """Close code if the handshake is refused. anyio wraps it in an ExceptionGroup over ASGI."""
    try:
        async with ws_client() as client, aconnect_ws(url, client):
            return None
    except* WebSocketDisconnect as group:
        exc = group.exceptions[0]
        assert isinstance(exc, WebSocketDisconnect)
        code = exc.code
    return code


@pytest.mark.parametrize("query", ["", "?token=garbage", f"?token={create_access_token(999)}"])
async def test_rejects_missing_invalid_or_unknown_user_token(live: Broadcaster, query: str) -> None:
    # 1008 = policy violation. Over ASGI a pre-accept close surfaces as this code; a real server
    # (uvicorn) answers the upgrade request with HTTP 403 instead.
    assert await rejection_code(f"/ws/live{query}") == 1008
    assert not live.subscribers


async def test_authenticated_client_receives_events(
    live: Broadcaster, auth_headers: Callable[[Role], Awaitable[dict[str, str]]]
) -> None:
    token = await token_for(auth_headers)
    ws: AsyncWebSocketSession  # aconnect_ws is generic over its session class; mypy needs help
    async with ws_client() as client, aconnect_ws(f"/ws/live?token={token}&tag_id=1", client) as ws:
        live.publish(reading(2))  # filtered out
        live.publish(READING)
        live.publish(ALARM)
        assert await asyncio.wait_for(ws.receive_json(), 2) == READING
        assert await asyncio.wait_for(ws.receive_json(), 2) == ALARM


async def test_disconnect_unsubscribes(
    live: Broadcaster, auth_headers: Callable[[Role], Awaitable[dict[str, str]]]
) -> None:
    token = await token_for(auth_headers)
    async with ws_client() as client:
        async with aconnect_ws(f"/ws/live?token={token}", client):
            assert len(live.subscribers) == 1
        for _ in range(50):  # the server notices the close asynchronously
            if not live.subscribers:
                break
            await asyncio.sleep(0.01)
        assert not live.subscribers
