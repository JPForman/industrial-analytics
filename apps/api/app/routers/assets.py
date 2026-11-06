from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.deps import DbSession, get_current_user, require_role
from app.models import Asset, AssetType, Role, Tag
from app.routers.common import Page, PageParams, commit_or_409, get_or_404
from app.schemas import AssetCreate, AssetOut, AssetUpdate, TagCreate, TagOut

# Router-level dependency: every endpoint here requires a logged-in user by default.
router = APIRouter(prefix="/assets", tags=["assets"], dependencies=[Depends(get_current_user)])

EngineerUp = Depends(require_role(Role.engineer))
AdminOnly = Depends(require_role(Role.admin))

ASSET_CONFLICT = "Asset name or Sparkplug identity (edge_node_id + device_id) already exists"


@router.get("", response_model=Page[AssetOut])
async def list_assets(
    db: DbSession,
    page: Annotated[PageParams, Depends()],
    asset_type: Annotated[AssetType | None, Query()] = None,
    site: Annotated[str | None, Query()] = None,
) -> Page[AssetOut]:
    filters = []
    if asset_type:
        filters.append(Asset.asset_type == asset_type)
    if site:
        filters.append(Asset.site == site)
    total = await db.scalar(select(func.count()).select_from(Asset).where(*filters)) or 0
    rows = await db.scalars(
        select(Asset).where(*filters).order_by(Asset.id).limit(page.limit).offset(page.offset)
    )
    items = [AssetOut.model_validate(r) for r in rows]
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "", response_model=AssetOut, status_code=status.HTTP_201_CREATED, dependencies=[EngineerUp]
)
async def create_asset(body: AssetCreate, db: DbSession) -> Asset:
    asset = Asset(**body.model_dump())
    db.add(asset)
    await commit_or_409(db, ASSET_CONFLICT)
    return asset


@router.get("/{asset_id}", response_model=AssetOut)
async def get_asset(asset_id: int, db: DbSession) -> Asset:
    return await get_or_404(db, Asset, asset_id)


@router.patch("/{asset_id}", response_model=AssetOut, dependencies=[EngineerUp])
async def update_asset(asset_id: int, body: AssetUpdate, db: DbSession) -> Asset:
    asset = await get_or_404(db, Asset, asset_id)
    # exclude_unset: only fields the client actually sent; omitted != null.
    for field, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(asset, field, value)
    await commit_or_409(db, ASSET_CONFLICT)
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[AdminOnly])
async def delete_asset(asset_id: int, db: DbSession) -> Response:
    # Eager-load tags: the ORM cascade must see them, and async can't lazy-load.
    asset = await db.scalar(
        select(Asset).where(Asset.id == asset_id).options(selectinload(Asset.tags))
    )
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    await db.delete(asset)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{asset_id}/tags", response_model=list[TagOut])
async def list_tags(asset_id: int, db: DbSession) -> list[Tag]:
    await get_or_404(db, Asset, asset_id)
    rows = await db.scalars(select(Tag).where(Tag.asset_id == asset_id).order_by(Tag.id))
    return list(rows)


@router.post(
    "/{asset_id}/tags",
    response_model=TagOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[EngineerUp],
)
async def create_tag(asset_id: int, body: TagCreate, db: DbSession) -> Tag:
    await get_or_404(db, Asset, asset_id)
    tag = Tag(asset_id=asset_id, **body.model_dump())
    db.add(tag)
    await commit_or_409(db, "Tag name already exists on this asset")
    return tag


@router.delete(
    "/{asset_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[EngineerUp]
)
async def delete_tag(asset_id: int, tag_id: int, db: DbSession) -> Response:
    tag = await get_or_404(db, Tag, tag_id)
    if tag.asset_id != asset_id:  # exists, but under another asset: report as not found
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    await db.delete(tag)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
