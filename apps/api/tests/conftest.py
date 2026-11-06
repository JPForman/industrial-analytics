import os
from collections.abc import AsyncIterator, Awaitable, Callable

# Must be set before importing the app: settings are read on first use.
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production-0123456789")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db import Base, get_db
from app.main import app
from app.models import Role, User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite://")


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    # StaticPool keeps one connection so in-memory SQLite is shared across the test.
    kwargs = {"poolclass": StaticPool} if TEST_DATABASE_URL.startswith("sqlite") else {}
    engine = create_async_engine(TEST_DATABASE_URL, **kwargs)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(db_session: AsyncSession) -> Callable[[Role], Awaitable[dict[str, str]]]:
    """Factory: `await auth_headers(Role.engineer)` -> headers for a fresh user of that role."""

    async def make(role: Role) -> dict[str, str]:
        user = User(email=f"{role.value}@example.com", password_hash="x", role=role)
        db_session.add(user)
        await db_session.commit()
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    return make
