from dataclasses import dataclass
from typing import Annotated

from fastapi import HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Base


class Page[T](BaseModel):
    """Envelope for list endpoints so clients can render page controls."""

    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass
class PageParams:
    limit: Annotated[int, Query(ge=1, le=200)] = 50  # hard cap protects the database
    offset: Annotated[int, Query(ge=0)] = 0


async def commit_or_409(db: AsyncSession, detail: str) -> None:
    """Let the unique constraint arbitrate duplicates (no racy SELECT-then-INSERT)."""
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from exc


async def get_or_404[M: Base](db: AsyncSession, model: type[M], pk: int) -> M:
    obj = await db.get(model, pk)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return obj
