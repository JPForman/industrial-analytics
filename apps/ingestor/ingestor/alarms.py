"""Alarm rules: a pure breach/transition decision, plus loading rules and open events."""

from dataclasses import dataclass
from enum import StrEnum

from app.models import AlarmEvent, AlarmOperator, AlarmRule
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Rule:
    id: int
    tag_id: int
    operator: AlarmOperator
    threshold: float
    severity: str


class Transition(StrEnum):
    OPEN = "open"
    CLEAR = "clear"


def breached(rule: Rule, value: float) -> bool:
    return value > rule.threshold if rule.operator is AlarmOperator.gt else value < rule.threshold


def transition(is_open: bool, is_breached: bool) -> Transition | None:
    """Edge-triggered: only the change of state matters, so one long excursion is ONE event,
    not one event per reading."""
    if is_breached and not is_open:
        return Transition.OPEN
    if not is_breached and is_open:
        return Transition.CLEAR
    return None


async def load_rules(session: AsyncSession) -> dict[int, list[Rule]]:
    rows = await session.scalars(select(AlarmRule).where(AlarmRule.enabled.is_(True)))
    by_tag: dict[int, list[Rule]] = {}
    for r in rows:
        rule = Rule(r.id, r.tag_id, r.operator, r.threshold, r.severity.value)
        by_tag.setdefault(r.tag_id, []).append(rule)
    return by_tag


async def load_open_events(session: AsyncSession) -> dict[int, int]:
    """rule_id -> open event id. Loaded on startup so a restart doesn't duplicate open alarms."""
    rows = await session.execute(
        select(AlarmEvent.rule_id, AlarmEvent.id).where(AlarmEvent.cleared_at.is_(None))
    )
    return {rule_id: event_id for rule_id, event_id in rows}
