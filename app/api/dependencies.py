from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token, verify_webhook_signature
from app.db.session import get_db
from app.models.user import User

# auto_error=False so a missing header gives our consistent 401 (not FastAPI's default).
bearer_scheme = HTTPBearer(auto_error=False, description="JWT from POST /auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise UnauthorizedError("Not authenticated")
    user = db.get(User, decode_access_token(credentials.credentials))
    if user is None:
        raise UnauthorizedError("User no longer exists")
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise ForbiddenError("Admin privileges required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]


async def verify_webhook_request(
    request: Request,
    x_webhook_signature: Annotated[
        str | None,
        Header(description="Hex HMAC-SHA256 of the raw request body, keyed with WEBHOOK_SECRET"),
    ] = None,
) -> None:
    """Rejects webhook calls that were not signed by the payment provider."""
    body = await request.body()
    if not verify_webhook_signature(body, x_webhook_signature):
        raise UnauthorizedError("Invalid webhook signature")
