from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.security import create_access_token, hash_password, verify_password
from app.deps import CurrentUser, DbSession
from app.models import User
from app.schemas import LoginRequest, SignupRequest, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, db: DbSession) -> User:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    # No role passed, so the model default (viewer) applies. Admins promote users separately.
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    await db.commit()
    return user


@router.post("/login", response_model=TokenOut)
async def login(body: LoginRequest, db: DbSession) -> TokenOut:
    user = await db.scalar(select(User).where(User.email == body.email))
    # Same error for unknown email and wrong password so responses don't reveal which emails exist.
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
