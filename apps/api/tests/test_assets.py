from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.models import Role

Headers = Callable[[Role], Awaitable[dict[str, str]]]

ASSET = {
    "name": "laser-1",
    "asset_type": "laser",
    "edge_node_id": "edge1",
    "device_id": "laser1",
}


async def create_asset(client: AsyncClient, headers: dict[str, str], **overrides: str) -> int:
    resp = await client.post("/assets", json=ASSET | overrides, headers=headers)
    assert resp.status_code == 201, resp.text
    asset_id: int = resp.json()["id"]
    return asset_id


async def test_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/assets")).status_code == 401


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.viewer, 403), (Role.engineer, 201), (Role.admin, 201)],
)
async def test_create_asset_role_matrix(
    client: AsyncClient, auth_headers: Headers, role: Role, expected: int
) -> None:
    resp = await client.post("/assets", json=ASSET, headers=await auth_headers(role))
    assert resp.status_code == expected


async def test_viewer_can_read(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    asset_id = await create_asset(client, eng)
    viewer = await auth_headers(Role.viewer)
    assert (await client.get(f"/assets/{asset_id}", headers=viewer)).status_code == 200
    assert (await client.get("/assets", headers=viewer)).json()["total"] == 1


async def test_duplicate_identity_conflicts(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    await create_asset(client, eng)
    resp = await client.post("/assets", json=ASSET | {"name": "other"}, headers=eng)
    assert resp.status_code == 409


async def test_pagination_and_filter(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    for i in range(5):
        await create_asset(client, eng, name=f"a{i}", device_id=f"d{i}")
    await create_asset(client, eng, name="press", device_id="p", asset_type="stamping_press")
    page = (await client.get("/assets?limit=2&offset=4", headers=eng)).json()
    assert (page["total"], len(page["items"]), page["offset"]) == (6, 2, 4)
    presses = (await client.get("/assets?asset_type=stamping_press", headers=eng)).json()
    assert presses["total"] == 1
    assert (await client.get("/assets?limit=1000", headers=eng)).status_code == 422


async def test_patch_changes_only_sent_fields(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    asset_id = await create_asset(client, eng)
    resp = await client.patch(f"/assets/{asset_id}", json={"site": "Columbus"}, headers=eng)
    assert resp.json()["site"] == "Columbus" and resp.json()["name"] == "laser-1"


async def test_delete_is_admin_only_and_cascades_tags(
    client: AsyncClient, auth_headers: Headers
) -> None:
    eng = await auth_headers(Role.engineer)
    asset_id = await create_asset(client, eng)
    await client.post(f"/assets/{asset_id}/tags", json={"name": "power", "unit": "W"}, headers=eng)
    assert (await client.delete(f"/assets/{asset_id}", headers=eng)).status_code == 403
    admin = await auth_headers(Role.admin)
    assert (await client.delete(f"/assets/{asset_id}", headers=admin)).status_code == 204
    assert (await client.get(f"/assets/{asset_id}", headers=admin)).status_code == 404
    assert (await client.delete(f"/assets/{asset_id}", headers=admin)).status_code == 404


async def test_tags_crud_and_uniqueness(client: AsyncClient, auth_headers: Headers) -> None:
    eng = await auth_headers(Role.engineer)
    asset_id = await create_asset(client, eng)
    url = f"/assets/{asset_id}/tags"
    created = await client.post(url, json={"name": "power", "unit": "W"}, headers=eng)
    assert created.status_code == 201
    assert (await client.post(url, json={"name": "power"}, headers=eng)).status_code == 409
    assert [t["name"] for t in (await client.get(url, headers=eng)).json()] == ["power"]
    assert (
        await client.post("/assets/999/tags", json={"name": "x"}, headers=eng)
    ).status_code == 404
    tag_id = created.json()["id"]
    other = await create_asset(client, eng, name="b", device_id="b")
    wrong = await client.delete(f"/assets/{other}/tags/{tag_id}", headers=eng)
    assert wrong.status_code == 404  # tag belongs to a different asset
    assert (await client.delete(f"{url}/{tag_id}", headers=eng)).status_code == 204
