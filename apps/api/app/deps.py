from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db import get_db
from app.models import Role, User

bearer = HTTPBearer(auto_error=False)

# Higher number = more privileged. Lets "engineer or above" be expressed simply.
_RANK = {Role.viewer: 0, Role.engineer: 1, Role.admin: 2}

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    user_id = decode_access_token(creds.credentials) if creds else None
    user = await db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(minimum: Role) -> Callable[[User], User]:
    """Dependency factory: `Depends(require_role(Role.engineer))` allows engineer and admin."""

    def checker(user: CurrentUser) -> User:
        if _RANK[user.role] < _RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return checker
