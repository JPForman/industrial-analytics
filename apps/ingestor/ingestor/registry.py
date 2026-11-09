"""Auto-registration: a DBIRTH creates/updates the Asset and its Tags. No manual config."""

from app.models import Asset, AssetType, Tag
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ingestor.state import DeviceBirth


async def upsert_device(
    session: AsyncSession, edge: str, device: str, birth: DeviceBirth
) -> dict[int, int]:
    """Returns alias -> tag_id for this device. Idempotent: rebirths reuse existing rows."""
    try:
        asset_type = AssetType(birth.asset_type or "")
    except ValueError:
        asset_type = AssetType.robot  # unknown types still ingest; fix the type via the API later
    await session.execute(
        insert(Asset)
        .values(name=device, asset_type=asset_type, edge_node_id=edge, device_id=device)
        .on_conflict_do_nothing()
    )
    asset_id = await session.scalar(
        select(Asset.id).where(Asset.edge_node_id == edge, Asset.device_id == device)
    )
    if asset_id is None:  # e.g. the name is taken by a different asset
        raise RuntimeError(f"could not register asset for {edge}/{device}")
    if not birth.metrics:
        await session.commit()
        return {}
    stmt = insert(Tag).values(
        [{"asset_id": asset_id, "name": m.name, "unit": m.unit} for m in birth.metrics]
    )
    rows = await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["asset_id", "name"], set_={"unit": stmt.excluded.unit}
        ).returning(Tag.name, Tag.id)
    )
    tag_by_name: dict[str, int] = {name: tag_id for name, tag_id in rows}
    await session.commit()
    return {m.alias: tag_by_name[m.name] for m in birth.metrics}
