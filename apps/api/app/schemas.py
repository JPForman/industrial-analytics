from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Role


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
