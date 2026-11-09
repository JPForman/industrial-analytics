from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AlarmEvent,
    AlarmOperator,
    AlarmRule,
    Asset,
    AssetType,
    Role,
    Severity,
    Tag,
)

Headers = Callable[[Role], Awaitable[dict[str, str]]]
T0 = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


async def seed(db: AsyncSession) -> dict[str, int]:
    """Two assets, one rule each, three events:
    laser: old cleared+acked, recent active; press: active warning."""
    laser = Asset(name="laser1", asset_type=AssetType.laser, edge_node_id="e", device_id="laser1")
    press = Asset(
        name="press1", asset_type=AssetType.stamping_press, edge_node_id="e", device_id="press1"
    )
    db.add_all([laser, press])
    await db.flush()
    power = Tag(asset_id=laser.id, name="power_w", unit="W")
    force = Tag(asset_id=press.id, name="force_kn", unit="kN")
    db.add_all([power, force])
    await db.flush()
    hot = AlarmRule(
        tag_id=power.id, operator=AlarmOperator.gt, threshold=1500, severity=Severity.critical
    )
    hard = AlarmRule(
        tag_id=force.id, operator=AlarmOperator.gt, threshold=800, severity=Severity.warning
    )
    db.add_all([hot, hard])
    await db.flush()
    old = AlarmEvent(
        rule_id=hot.id,
        value=1600,
        triggered_at=T0,
        cleared_at=T0 + timedelta(minutes=1),
        acknowledged_at=T0 + timedelta(minutes=2),
    )
    recent = AlarmEvent(rule_id=hot.id, value=1700, triggered_at=T0 + timedelta(hours=1))
    pressed = AlarmEvent(rule_id=hard.id, value=900, triggered_at=T0 + timedelta(minutes=30))
    db.add_all([old, recent, pressed])
    await db.commit()
    return {"laser": laser.id, "old": old.id, "recent": recent.id, "pressed": pressed.id}


async def test_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/alarms")).status_code == 401


async def test_list_is_flattened_and_newest_first(
    client: AsyncClient, db_session: AsyncSession, auth_headers: Headers
) -> None:
    ids = await seed(db_session)
    resp = await client.get("/alarms", headers=await auth_headers(Role.viewer))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert [a["id"] for a in body["items"]] == [ids["recent"], ids["pressed"], ids["old"]]
    first = body["items"][0]
    assert first["asset_name"] == "laser1" and first["tag_name"] == "power_w"
    assert first["unit"] == "W" and first["operator"] == "gt" and first["threshold"] == 1500
    assert first["severity"] == "critical" and first["cleared_at"] is None
    assert first["triggered_at"].endswith(("+00:00", "Z"))


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("state=active", ["recent", "pressed"]),
        ("state=unacknowledged", ["recent", "pressed"]),
        ("severity=critical", ["recent", "old"]),
        ("state=active&severity=warning", ["pressed"]),
    ],
)
async def test_filters(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: Headers,
    query: str,
    expected: list[str],
) -> None:
    ids = await seed(db_session)
    resp = await client.get(f"/alarms?{query}", headers=await auth_headers(Role.viewer))
    assert [a["id"] for a in resp.json()["items"]] == [ids[k] for k in expected]


async def test_filter_by_asset(
    client: AsyncClient, db_session: AsyncSession, auth_headers: Headers
) -> None:
    ids = await seed(db_session)
    resp = await client.get(
        f"/alarms?asset_id={ids['laser']}", headers=await auth_headers(Role.viewer)
    )
    assert resp.json()["total"] == 2


async def test_acknowledge_once(
    client: AsyncClient, db_session: AsyncSession, auth_headers: Headers
) -> None:
    ids = await seed(db_session)
    eng = await auth_headers(Role.engineer)
    url = f"/alarms/{ids['recent']}/acknowledge"
    resp = await client.post(url, headers=eng)
    assert resp.status_code == 200
    body = resp.json()
    assert body["acknowledged_at"] is not None and body["acknowledged_by_id"] is not None
    assert body["cleared_at"] is None  # acking takes ownership; it doesn't clear the condition
    assert (await client.post(url, headers=eng)).status_code == 409


async def test_acknowledge_unknown_is_404(client: AsyncClient, auth_headers: Headers) -> None:
    resp = await client.post("/alarms/999/acknowledge", headers=await auth_headers(Role.admin))
    assert resp.status_code == 404


@pytest.mark.parametrize(("role", "code"), [(Role.viewer, 403), (Role.engineer, 200)])
async def test_acknowledge_role_matrix(
    client: AsyncClient, db_session: AsyncSession, auth_headers: Headers, role: Role, code: int
) -> None:
    ids = await seed(db_session)
    resp = await client.post(
        f"/alarms/{ids['pressed']}/acknowledge", headers=await auth_headers(role)
    )
    assert resp.status_code == code
