from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.deps import DbSession, get_current_user, require_role
from app.models import Reading, Role, Tag
from app.routers.common import get_or_404
from app.schemas import IngestResult, ReadingOut, ReadingsIngest, ReadingsPage

router = APIRouter(tags=["readings"], dependencies=[Depends(get_current_user)])


@router.post(
    "/readings",
    response_model=IngestResult,
    dependencies=[Depends(require_role(Role.engineer))],
)
async def ingest_readings(body: ReadingsIngest, db: DbSession) -> IngestResult:
    """Bulk insert. Idempotent: re-sending the same (tag_id, ts) is ignored, not an error."""
    tag_ids = {r.tag_id for r in body.readings}
    known = set(await db.scalars(select(Tag.id).where(Tag.id.in_(tag_ids))))
    if unknown := sorted(tag_ids - known):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown tag ids: {unknown}")

    # ON CONFLICT is dialect-specific SQL; production is Postgres, SQLite serves fast tests.
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    stmt = (
        insert(Reading)
        .values([r.model_dump() for r in body.readings])
        .on_conflict_do_nothing(index_elements=["tag_id", "ts"])
    )
    result = await db.execute(stmt)
    await db.commit()
    return IngestResult(received=len(body.readings), inserted=result.rowcount)  # type: ignore[attr-defined]


@router.get("/tags/{tag_id}/readings", response_model=ReadingsPage)
async def list_readings(
    tag_id: int,
    db: DbSession,
    start: Annotated[AwareDatetime, Query(description="Inclusive lower bound")],
    end: Annotated[AwareDatetime, Query(description="Exclusive upper bound")],
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    cursor: Annotated[
        AwareDatetime | None, Query(description="next_cursor from the last page")
    ] = None,
) -> ReadingsPage:
    """Raw points, oldest first, keyset-paginated. start/end are required so TimescaleDB
    can skip chunks outside the range."""
    if end <= start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end must be after start")
    await get_or_404(db, Tag, tag_id)

    lower = [Reading.ts >= start] if cursor is None else [Reading.ts > max(cursor, start)]
    rows = list(
        await db.scalars(
            select(Reading)
            .where(Reading.tag_id == tag_id, *lower, Reading.ts < end)
            .order_by(Reading.ts)
            .limit(limit)
        )
    )
    items = [ReadingOut.model_validate(r) for r in rows]
    next_cursor: datetime | None = items[-1].ts if len(items) == limit else None
    return ReadingsPage(items=items, next_cursor=next_cursor)
