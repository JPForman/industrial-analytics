from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.base import Base
from app.core.config import get_settings

__all__ = ["Base", "SessionLocal", "engine", "get_db"]

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """One session per request; closed automatically afterwards."""
    async with SessionLocal() as session:
        yield session
