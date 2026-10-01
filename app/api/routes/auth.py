from fastapi import APIRouter, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse
from app.schemas.common import error_responses
from app.schemas.user import UserRead
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/signup",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses=error_responses(409),
)
def signup(data: SignupRequest, db: DbSession) -> UserRead:
    """Register a new user. Emails are normalised to lower case and must be unique (409
    otherwise). Passwords need 8+ characters with at least one letter and one digit."""
    return UserRead.model_validate(auth_service.signup(db, data))


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and get a JWT",
    responses=error_responses(401),
)
def login(data: LoginRequest, db: DbSession) -> TokenResponse:
    """Exchange email + password for a bearer token. Send it as `Authorization: Bearer <token>`."""
    return TokenResponse(access_token=auth_service.login(db, data))


@router.get(
    "/me",
    response_model=UserRead,
    summary="Current user",
    responses=error_responses(401),
)
def me(user: CurrentUser) -> UserRead:
    """Return the authenticated user's profile."""
    return UserRead.model_validate(user)
