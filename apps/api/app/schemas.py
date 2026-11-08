from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import AlarmOperator, AssetType, BatchStatus, Role, Severity


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt ignores bytes past 72


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    """Response shape. No password_hash field, so it can never leak."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: Role


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    asset_type: AssetType
    site: str = Field(default="Buffalo", min_length=1, max_length=100)
    edge_node_id: str = Field(min_length=1, max_length=100)
    device_id: str = Field(min_length=1, max_length=100)


class AssetUpdate(BaseModel):
    """All fields optional: PATCH only changes what the client sent."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    asset_type: AssetType | None = None
    site: str | None = Field(default=None, min_length=1, max_length=100)


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    asset_type: AssetType
    site: str
    edge_node_id: str
    device_id: str
    created_at: datetime


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    unit: str = Field(default="", max_length=32)


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: int
    name: str
    unit: str


class BatchCreate(BaseModel):
    asset_id: int
    name: str = Field(min_length=1, max_length=200)


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: int
    name: str
    status: BatchStatus
    started_at: datetime
    ended_at: datetime | None


class ReadingIn(BaseModel):
    tag_id: int
    ts: AwareDatetime  # timezone required: a naive timestamp is ambiguous
    value: float = Field(allow_inf_nan=False)  # NaN/Infinity would poison aggregates


class ReadingsIngest(BaseModel):
    readings: list[ReadingIn] = Field(min_length=1, max_length=1000)


class IngestResult(BaseModel):
    received: int
    inserted: int  # received - inserted = duplicates that were safely ignored


class ReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    value: float

    @field_validator("ts")
    @classmethod
    def _assume_utc(cls, v: datetime) -> datetime:
        # We store UTC. Some drivers (SQLite) hand back naive datetimes; Postgres is aware.
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class ReadingsPage(BaseModel):
    items: list[ReadingOut]
    next_cursor: datetime | None  # pass as ?cursor= to get the next page; null = no more


class BucketSize(StrEnum):
    """Allowlist of bucket widths: bounded input, predictable cost."""

    s10 = "10s"
    m1 = "1m"
    m5 = "5m"
    m15 = "15m"
    h1 = "1h"
    d1 = "1d"

    @property
    def delta(self) -> timedelta:
        return _BUCKET_DELTAS[self]


_BUCKET_DELTAS = {
    BucketSize.s10: timedelta(seconds=10),
    BucketSize.m1: timedelta(minutes=1),
    BucketSize.m5: timedelta(minutes=5),
    BucketSize.m15: timedelta(minutes=15),
    BucketSize.h1: timedelta(hours=1),
    BucketSize.d1: timedelta(days=1),
}


class AggregateBucket(BaseModel):
    bucket: datetime  # start of the bucket
    avg: float
    min: float
    max: float
    count: int

    @field_validator("bucket")
    @classmethod
    def _assume_utc(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=UTC)


class AlarmState(StrEnum):
    active = "active"  # not cleared yet: the condition is still present
    unacknowledged = "unacknowledged"  # nobody has taken ownership (active or cleared)
    all = "all"


class AlarmOut(BaseModel):
    """An alarm event flattened with its rule, tag and asset, so the UI needs one request."""

    id: int
    rule_id: int
    tag_id: int
    tag_name: str
    unit: str
    asset_id: int
    asset_name: str
    operator: AlarmOperator
    threshold: float
    severity: Severity
    value: float
    triggered_at: datetime
    cleared_at: datetime | None
    acknowledged_at: datetime | None
    acknowledged_by_id: int | None

    @field_validator("triggered_at", "cleared_at", "acknowledged_at")
    @classmethod
    def _assume_utc(cls, v: datetime | None) -> datetime | None:
        return v if v is None or v.tzinfo else v.replace(tzinfo=UTC)
