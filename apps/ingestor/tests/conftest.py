import os
from collections.abc import AsyncIterator

import app.models  # noqa: F401  (registers tables)
import pytest
from app.base import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

needs_postgres = pytest.mark.skipif(
    not TEST_DATABASE_URL.startswith("postgresql"), reason="set TEST_DATABASE_URL to a Postgres DB"
)


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
