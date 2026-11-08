"""Alarm events: list with filters, and acknowledge.

Events are created and cleared only by the ingestor (it owns alarm state, ADR 0004). Users can
only acknowledge, which records who took ownership; it never clears the condition.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select, update

from app.deps import DbSession, get_current_user, require_role
from app.models import AlarmEvent, AlarmRule, Asset, Role, Severity, Tag, User
from app.routers.common import Page, PageParams, get_or_404
from app.schemas import AlarmOut, AlarmState

router = APIRouter(prefix="/alarms", tags=["alarms"], dependencies=[Depends(get_current_user)])

Engineer = Annotated[User, Depends(require_role(Role.engineer))]


def _alarm_select() -> Select[*tuple[Any, ...]]:
    """One row per event, joined to its rule, tag and asset (no N+1 lookups)."""
    return (
        select(
            AlarmEvent.id,
            AlarmEvent.rule_id,
            AlarmRule.tag_id,
            Tag.name.label("tag_name"),
            Tag.unit,
            Tag.asset_id,
            Asset.name.label("asset_name"),
            AlarmRule.operator,
            AlarmRule.threshold,
            AlarmRule.severity,
            AlarmEvent.value,
            AlarmEvent.triggered_at,
            AlarmEvent.cleared_at,
            AlarmEvent.acknowledged_at,
            AlarmEvent.acknowledged_by_id,
        )
        .join(AlarmRule, AlarmEvent.rule_id == AlarmRule.id)
        .join(Tag, AlarmRule.tag_id == Tag.id)
        .join(Asset, Tag.asset_id == Asset.id)
    )


@router.get("", response_model=Page[AlarmOut])
async def list_alarms(
    db: DbSession,
    page: Annotated[PageParams, Depends()],
    state: Annotated[AlarmState, Query()] = AlarmState.all,
    asset_id: Annotated[int | None, Query()] = None,
    severity: Annotated[Severity | None, Query()] = None,
) -> Page[AlarmOut]:
    query = _alarm_select()
    if state is AlarmState.active:
        query = query.where(AlarmEvent.cleared_at.is_(None))
    elif state is AlarmState.unacknowledged:
        query = query.where(AlarmEvent.acknowledged_at.is_(None))
    if asset_id is not None:
        query = query.where(Tag.asset_id == asset_id)
    if severity is not None:
        query = query.where(AlarmRule.severity == severity)

    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await db.execute(
        query.order_by(AlarmEvent.triggered_at.desc(), AlarmEvent.id.desc())  # newest first
        .limit(page.limit)
        .offset(page.offset)
    )
    items = [AlarmOut.model_validate(dict(r._mapping)) for r in rows]
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


async def _get_alarm(db: DbSession, event_id: int) -> AlarmOut:
    row = (await db.execute(_alarm_select().where(AlarmEvent.id == event_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "AlarmEvent not found")
    return AlarmOut.model_validate(dict(row._mapping))


@router.get("/{event_id}", response_model=AlarmOut)
async def get_alarm(event_id: int, db: DbSession) -> AlarmOut:
    return await _get_alarm(db, event_id)


@router.post("/{event_id}/acknowledge", response_model=AlarmOut)
async def acknowledge_alarm(event_id: int, db: DbSession, user: Engineer) -> AlarmOut:
    """Atomic: `UPDATE ... WHERE acknowledged_at IS NULL`, so two operators acking at once
    can't both win (or overwrite who acked first). The loser gets 409."""
    result = await db.execute(
        update(AlarmEvent)
        .where(AlarmEvent.id == event_id, AlarmEvent.acknowledged_at.is_(None))
        .values(acknowledged_at=datetime.now(UTC), acknowledged_by_id=user.id)
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        await get_or_404(db, AlarmEvent, event_id)  # 404 if it doesn't exist
        raise HTTPException(status.HTTP_409_CONFLICT, "Alarm is already acknowledged")
    await db.commit()
    return await _get_alarm(db, event_id)
