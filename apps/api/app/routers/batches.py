from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update

from app.deps import DbSession, get_current_user, require_role
from app.models import Asset, Batch, BatchStatus, Role
from app.routers.common import Page, PageParams, commit_or_409, get_or_404
from app.schemas import BatchCreate, BatchOut

router = APIRouter(prefix="/batches", tags=["batches"], dependencies=[Depends(get_current_user)])

EngineerUp = Depends(require_role(Role.engineer))

RUNNING_CONFLICT = "This asset already has a running batch"


@router.get("", response_model=Page[BatchOut])
async def list_batches(
    db: DbSession,
    page: Annotated[PageParams, Depends()],
    asset_id: Annotated[int | None, Query()] = None,
    batch_status: Annotated[BatchStatus | None, Query(alias="status")] = None,
) -> Page[BatchOut]:
    filters = []
    if asset_id is not None:
        filters.append(Batch.asset_id == asset_id)
    if batch_status:
        filters.append(Batch.status == batch_status)
    total = await db.scalar(select(func.count()).select_from(Batch).where(*filters)) or 0
    rows = await db.scalars(
        select(Batch)
        .where(*filters)
        .order_by(Batch.started_at.desc(), Batch.id.desc())  # newest first
        .limit(page.limit)
        .offset(page.offset)
    )
    items = [BatchOut.model_validate(r) for r in rows]
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "", response_model=BatchOut, status_code=status.HTTP_201_CREATED, dependencies=[EngineerUp]
)
async def start_batch(body: BatchCreate, db: DbSession) -> Batch:
    await get_or_404(db, Asset, body.asset_id)
    # status and started_at are server-controlled; the client cannot set them.
    batch = Batch(asset_id=body.asset_id, name=body.name)
    db.add(batch)
    await commit_or_409(db, RUNNING_CONFLICT)  # the partial unique index decides
    await db.refresh(batch)  # load the server-generated started_at
    return batch


@router.get("/{batch_id}", response_model=BatchOut)
async def get_batch(batch_id: int, db: DbSession) -> Batch:
    return await get_or_404(db, Batch, batch_id)


async def _finish(db: DbSession, batch_id: int, new_status: BatchStatus) -> Batch:
    """State machine: the only legal transitions are running -> completed | aborted.

    The check and the write are ONE atomic statement (`UPDATE ... WHERE status = 'running'`),
    so two simultaneous requests cannot both succeed: the loser updates zero rows.
    """
    result = await db.execute(
        update(Batch)
        .where(Batch.id == batch_id, Batch.status == BatchStatus.running)
        .values(status=new_status, ended_at=datetime.now(UTC))
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        # Nothing changed: either it doesn't exist, or it was already finished.
        batch = await get_or_404(db, Batch, batch_id)
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Batch is already {batch.status.value}; cannot change it"
        )
    await db.commit()
    # populate_existing: bypass the session's cached copy, which still shows the old status.
    finished = await db.get(Batch, batch_id, populate_existing=True)
    assert finished is not None
    return finished


@router.post("/{batch_id}/complete", response_model=BatchOut, dependencies=[EngineerUp])
async def complete_batch(batch_id: int, db: DbSession) -> Batch:
    return await _finish(db, batch_id, BatchStatus.completed)


@router.post("/{batch_id}/abort", response_model=BatchOut, dependencies=[EngineerUp])
async def abort_batch(batch_id: int, db: DbSession) -> Batch:
    return await _finish(db, batch_id, BatchStatus.aborted)
