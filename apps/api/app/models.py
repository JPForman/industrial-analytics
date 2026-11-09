import enum
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.base import Base


class Role(enum.StrEnum):
    """RBAC roles, ordered least to most privileged."""

    viewer = "viewer"
    engineer = "engineer"
    admin = "admin"


class AssetType(enum.StrEnum):
    laser = "laser"
    stamping_press = "stamping_press"
    printer_3d = "printer_3d"
    robot = "robot"


class BatchStatus(enum.StrEnum):
    running = "running"
    completed = "completed"
    aborted = "aborted"


class AlarmOperator(enum.StrEnum):
    gt = "gt"
    lt = "lt"


class Severity(enum.StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(default=Role.viewer)


class Asset(Base):
    """A machine on the shop floor. edge_node_id/device_id map to Sparkplug B topics."""

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("edge_node_id", "device_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    asset_type: Mapped[AssetType]
    site: Mapped[str] = mapped_column(String(100), default="Buffalo")
    edge_node_id: Mapped[str] = mapped_column(String(100))
    device_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tags: Mapped[list[Tag]] = relationship(back_populates="asset", cascade="all, delete-orphan")


class Tag(Base):
    """One measurable signal on an asset (a Sparkplug metric), e.g. 'laser/power_w'."""

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("asset_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(32), default="")

    asset: Mapped[Asset] = relationship(back_populates="tags")


class Reading(Base):
    """Narrow time-series row. A TimescaleDB hypertable partitioned on `ts` (see migration).

    The composite primary key (tag_id, ts) is required to include the partition column,
    and makes redelivered MQTT messages idempotent.
    """

    __tablename__ = "readings"

    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class Batch(Base):
    """A production run on one asset, defined by a time window."""

    __tablename__ = "batches"
    __table_args__ = (
        # Invariant enforced by the database: at most one running batch per asset.
        Index(
            "uq_batches_one_running_per_asset",
            "asset_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[BatchStatus] = mapped_column(default=BatchStatus.running)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlarmRule(Base):
    """Configuration: fire when tag value <operator> threshold."""

    __tablename__ = "alarm_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True)
    operator: Mapped[AlarmOperator]
    threshold: Mapped[float] = mapped_column(Float)
    severity: Mapped[Severity] = mapped_column(default=Severity.warning)
    enabled: Mapped[bool] = mapped_column(default=True)


class AlarmEvent(Base):
    """History: a rule fired. cleared_at is set when the value returns to normal."""

    __tablename__ = "alarm_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alarm_rules.id", ondelete="CASCADE"), index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    value: Mapped[float] = mapped_column(Float)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
