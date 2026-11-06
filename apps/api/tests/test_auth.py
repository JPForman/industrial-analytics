from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import require_role
from app.models import Role, User

CREDS = {"email": "eng@example.com", "password": "correct-horse"}


async def signup_and_login(client: AsyncClient) -> str:
    await client.post("/auth/signup", json=CREDS)
    resp = await client.post("/auth/login", json=CREDS)
    token: str = resp.json()["access_token"]
    return token


async def test_signup_assigns_viewer_and_hides_hash(client: AsyncClient) -> None:
    resp = await client.post("/auth/signup", json=CREDS)
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "viewer"
    assert "password_hash" not in body and "password" not in body


async def test_duplicate_signup_conflicts(client: AsyncClient) -> None:
    await client.post("/auth/signup", json=CREDS)
    assert (await client.post("/auth/signup", json=CREDS)).status_code == 409


async def test_login_errors_are_indistinguishable(client: AsyncClient) -> None:
    await client.post("/auth/signup", json=CREDS)
    wrong_pw = await client.post("/auth/login", json={**CREDS, "password": "wrong-password"})
    no_user = await client.post("/auth/login", json={**CREDS, "email": "nobody@example.com"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


async def test_me_requires_valid_token(client: AsyncClient) -> None:
    assert (await client.get("/auth/me")).status_code == 401
    assert (
        await client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    ).status_code == 401
    token = await signup_and_login(client)
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200 and resp.json()["email"] == CREDS["email"]


async def test_require_role_enforces_rank(db_session: AsyncSession) -> None:
    import pytest
    from fastapi import HTTPException

    checker = require_role(Role.engineer)
    viewer = User(email="v@example.com", password_hash="x", role=Role.viewer)
    admin = User(email="a@example.com", password_hash="x", role=Role.admin)
    with pytest.raises(HTTPException) as exc:
        checker(viewer)
    assert exc.value.status_code == 403
    assert checker(admin) is admin


async def test_health_and_ready(client: AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/ready")).json() == {"status": "ready"}
