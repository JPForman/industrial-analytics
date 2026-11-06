import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import get_db
from app.main import app
from app.models import Role
from tests.conftest import TEST_DATABASE_URL

Headers = Callable[[Role], Awaitable[dict[str, str]]]


async def make_asset(client: AsyncClient, headers: dict[str, str], n: int = 1) -> int:
    resp = await client.post(
        "/assets",
        json={
            "name": f"press-{n}",
            "asset_type": "stamping_press",
            "edge_node_id": "e1",
            "device_id": f"d{n}",
        },
        headers=headers,
    )
    asset_id: int = resp.json()["id"]
    return asset_id


async def start(
    client: AsyncClient, headers: dict[str, str], asset_id: int, name: str = "run"
) -> int:
    resp = await client.post("/batches", json={"asset_id": asset_id, "name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    batch_id: int = resp.json()["id"]
    return batch_id


async def test_start_batch_is_server_controlled(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    asset_id = await make_asset(client, eng)
    resp = await client.post(
        "/batches",
        # a client trying to set server-owned fields: ignored, not an error
        json={
            "asset_id": asset_id,
            "name": "Lot 42",
            "status": "completed",
            "ended_at": "2020-01-01T00:00:00Z",
        },
        headers=eng,
    )
    body = resp.json()
    assert resp.status_code == 201
    assert body["status"] == "running" and body["ended_at"] is None
    assert body["started_at"] is not None


async def test_only_engineers_can_start(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    asset_id = await make_asset(client, eng)
    viewer = await auth_headers(Role.viewer)
    resp = await client.post("/batches", json={"asset_id": asset_id, "name": "x"}, headers=viewer)
    assert resp.status_code == 403
    assert (await client.get("/batches", headers=viewer)).status_code == 200


async def test_unknown_asset_is_404(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    resp = await client.post("/batches", json={"asset_id": 999, "name": "x"}, headers=eng)
    assert resp.status_code == 404


async def test_one_running_batch_per_asset(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    asset_id = await make_asset(client, eng)
    await start(client, eng, asset_id)
    dup = await client.post("/batches", json={"asset_id": asset_id, "name": "again"}, headers=eng)
    assert dup.status_code == 409
    # a different asset is unaffected
    other = await make_asset(client, eng, n=2)
    await start(client, eng, other)


@pytest.mark.parametrize(("action", "final"), [("complete", "completed"), ("abort", "aborted")])
async def test_finish_transitions(
    client: AsyncClient, auth_headers: Headers, action: str, final: str
) -> None:
    eng = await auth_headers(Role.engineer)
    asset_id = await make_asset(client, eng)
    batch_id = await start(client, eng, asset_id)
    resp = await client.post(f"/batches/{batch_id}/{action}", headers=eng)
    assert resp.status_code == 200
    assert resp.json()["status"] == final and resp.json()["ended_at"] is not None
    # state machine: a finished batch cannot be finished again, either way
    for again in ("complete", "abort"):
        assert (await client.post(f"/batches/{batch_id}/{again}", headers=eng)).status_code == 409


async def test_finishing_frees_the_asset_for_a_new_batch(
    client: AsyncClient, auth_headers: Headers
) -> None:
    eng = await auth_headers(Role.engineer)
    asset_id = await make_asset(client, eng)
    first = await start(client, eng, asset_id, "first")
    await client.post(f"/batches/{first}/complete", headers=eng)
    await start(client, eng, asset_id, "second")  # partial index only covers running rows


async def test_viewer_cannot_finish(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    batch_id = await start(client, eng, await make_asset(client, eng))
    viewer = await auth_headers(Role.viewer)
    assert (await client.post(f"/batches/{batch_id}/complete", headers=viewer)).status_code == 403
    assert (await client.post("/batches/999/complete", headers=eng)).status_code == 404


async def test_list_filters_and_newest_first(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    a1, a2 = await make_asset(client, eng, 1), await make_asset(client, eng, 2)
    done = await start(client, eng, a1, "old")
    await client.post(f"/batches/{done}/complete", headers=eng)
    await start(client, eng, a1, "newer")
    await start(client, eng, a2, "other-asset")
    everything = (await client.get("/batches", headers=eng)).json()
    assert everything["total"] == 3
    assert everything["items"][0]["name"] == "other-asset"  # newest first
    running = (await client.get("/batches?status=running", headers=eng)).json()
    assert running["total"] == 2
    mine = (await client.get(f"/batches?asset_id={a1}", headers=eng)).json()
    assert {b["name"] for b in mine["items"]} == {"old", "newer"}
    assert (await client.get("/batches?status=bogus", headers=eng)).status_code == 422


@pytest.fixture
async def concurrent_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Client whose every request gets its OWN DB session, so requests can truly interleave.

    (The normal `client` fixture shares one session, which hides races.) Needs real Postgres.
    """
    engine = create_async_engine(TEST_DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def per_request() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = per_request
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.skipif(
    TEST_DATABASE_URL.startswith("sqlite"), reason="needs real Postgres for true concurrency"
)
async def test_simultaneous_finish_has_exactly_one_winner(
    concurrent_client: AsyncClient, auth_headers: Headers
) -> None:
    eng = await auth_headers(Role.engineer)
    for n in range(10):  # a race may not show on every attempt, so use a fresh batch each round
        asset_id = await make_asset(concurrent_client, eng, n=n)
        batch_id = await start(concurrent_client, eng, asset_id)
        done, aborted = await asyncio.gather(
            concurrent_client.post(f"/batches/{batch_id}/complete", headers=eng),
            concurrent_client.post(f"/batches/{batch_id}/abort", headers=eng),
        )
        assert sorted([done.status_code, aborted.status_code]) == [200, 409], f"round {n}"
        winner = done if done.status_code == 200 else aborted
        final = (await concurrent_client.get(f"/batches/{batch_id}", headers=eng)).json()
        assert final["status"] == winner.json()["status"]  # what the winner was told is true
