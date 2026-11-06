from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AssetType, Reading, Tag


def make_asset(**overrides: str) -> Asset:
    fields = {"name": "laser-1", "edge_node_id": "edge1", "device_id": "laser1"}
    return Asset(asset_type=AssetType.laser, **(fields | overrides))


async def test_asset_defaults_and_tag_relationship(db_session: AsyncSession) -> None:
    asset = make_asset()
    asset.tags.append(Tag(name="laser/power_w", unit="W"))
    db_session.add(asset)
    await db_session.commit()
    assert asset.site == "Buffalo"
    assert asset.tags[0].unit == "W"


async def test_asset_sparkplug_identity_is_unique(db_session: AsyncSession) -> None:
    db_session.add(make_asset(name="a"))
    await db_session.commit()
    db_session.add(make_asset(name="b"))  # same edge_node_id + device_id
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_tag_name_unique_per_asset(db_session: AsyncSession) -> None:
    asset = make_asset()
    asset.tags.extend([Tag(name="temp"), Tag(name="temp")])
    db_session.add(asset)
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_reading_key_makes_redelivery_idempotent(db_session: AsyncSession) -> None:
    asset = make_asset()
    asset.tags.append(Tag(name="temp"))
    db_session.add(asset)
    await db_session.commit()
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    tag_id = asset.tags[0].id
    db_session.add(Reading(tag_id=tag_id, ts=ts, value=1.0))
    await db_session.commit()
    db_session.add(Reading(tag_id=tag_id, ts=ts, value=2.0))  # same (tag_id, ts)
    with pytest.raises(IntegrityError):
        await db_session.commit()
