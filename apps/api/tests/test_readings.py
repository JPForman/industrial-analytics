from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models import Role

Headers = Callable[[Role], Awaitable[dict[str, str]]]

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def iso(offset_s: int) -> str:
    return (T0 + timedelta(seconds=offset_s)).isoformat()


def points(tag_id: int, n: int) -> list[dict[str, object]]:
    return [{"tag_id": tag_id, "ts": iso(i), "value": float(i)} for i in range(n)]


async def make_tag(client: AsyncClient, headers: dict[str, str]) -> int:
    asset = await client.post(
        "/assets",
        json={"name": "laser-1", "asset_type": "laser", "edge_node_id": "e", "device_id": "d"},
        headers=headers,
    )
    tag = await client.post(
        f"/assets/{asset.json()['id']}/tags", json={"name": "power", "unit": "W"}, headers=headers
    )
    tag_id: int = tag.json()["id"]
    return tag_id


async def test_ingest_role_matrix(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    tag_id = await make_tag(client, eng)
    body = {"readings": points(tag_id, 1)}
    assert (await client.post("/readings", json=body)).status_code == 401
    viewer = await auth_headers(Role.viewer)
    assert (await client.post("/readings", json=body, headers=viewer)).status_code == 403
    assert (await client.post("/readings", json=body, headers=eng)).status_code == 200


async def test_ingest_is_idempotent(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    tag_id = await make_tag(client, eng)
    body = {"readings": points(tag_id, 5)}
    first = (await client.post("/readings", json=body, headers=eng)).json()
    again = (await client.post("/readings", json=body, headers=eng)).json()  # redelivery
    assert first == {"received": 5, "inserted": 5}
    assert again == {"received": 5, "inserted": 0}
    page = (
        await client.get(
            f"/tags/{tag_id}/readings", params={"start": iso(0), "end": iso(100)}, headers=eng
        )
    ).json()
    assert len(page["items"]) == 5  # no duplicates stored


@pytest.mark.parametrize(
    "bad",
    [
        {"tag_id": 999, "ts": iso(0), "value": 1.0},  # unknown tag
        {"tag_id": 1, "ts": "2026-01-01T00:00:00", "value": 1.0},  # naive timestamp
        {"tag_id": 1, "ts": iso(0), "value": "NaN"},  # NaN rejected
    ],
)
async def test_ingest_validation(
    client: AsyncClient, auth_headers: Headers, bad: dict[str, object]
) -> None:
    eng = await auth_headers(Role.engineer)
    await make_tag(client, eng)  # tag id 1 exists
    resp = await client.post("/readings", json={"readings": [bad]}, headers=eng)
    assert resp.status_code == 422


async def test_ingest_batch_size_limits(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    tag_id = await make_tag(client, eng)
    assert (await client.post("/readings", json={"readings": []}, headers=eng)).status_code == 422
    too_many = {"readings": points(tag_id, 1001)}
    assert (await client.post("/readings", json=too_many, headers=eng)).status_code == 422


async def test_cursor_pagination_visits_every_point_once(
    client: AsyncClient, auth_headers: Headers
) -> None:
    eng = await auth_headers(Role.engineer)
    tag_id = await make_tag(client, eng)
    await client.post("/readings", json={"readings": points(tag_id, 25)}, headers=eng)
    seen: list[float] = []
    params: dict[str, str | int] = {"start": iso(0), "end": iso(1000), "limit": 10}
    pages = 0
    while True:
        page = (await client.get(f"/tags/{tag_id}/readings", params=params, headers=eng)).json()
        seen += [p["value"] for p in page["items"]]
        pages += 1
        if page["next_cursor"] is None:
            break
        params["cursor"] = page["next_cursor"]
    assert seen == [float(i) for i in range(25)]  # in order, none missing, none repeated
    assert pages == 3


async def test_time_range_is_start_inclusive_end_exclusive(
    client: AsyncClient, auth_headers: Headers
) -> None:
    eng = await auth_headers(Role.engineer)
    tag_id = await make_tag(client, eng)
    await client.post("/readings", json={"readings": points(tag_id, 10)}, headers=eng)
    resp = await client.get(
        f"/tags/{tag_id}/readings", params={"start": iso(2), "end": iso(5)}, headers=eng
    )
    assert [p["value"] for p in resp.json()["items"]] == [2.0, 3.0, 4.0]


async def test_query_requires_bounded_valid_range_and_known_tag(
    client: AsyncClient, auth_headers: Headers
) -> None:
    eng = await auth_headers(Role.engineer)
    tag_id = await make_tag(client, eng)
    url = f"/tags/{tag_id}/readings"
    assert (await client.get(url, headers=eng)).status_code == 422  # start/end are required
    backwards = {"start": iso(10), "end": iso(5)}
    assert (await client.get(url, params=backwards, headers=eng)).status_code == 422
    ok = {"start": iso(0), "end": iso(5)}
    assert (await client.get("/tags/999/readings", params=ok, headers=eng)).status_code == 404
    viewer = await auth_headers(Role.viewer)
    assert (await client.get(url, params=ok, headers=viewer)).status_code == 200
