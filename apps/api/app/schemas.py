from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import AssetType, Role


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
