import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, SignupRequest

logger = logging.getLogger(__name__)


def signup(db: Session, data: SignupRequest) -> User:
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name.strip(),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # The UNIQUE(email) constraint is the source of truth (no check-then-insert race).
        db.rollback()
        raise ConflictError("A user with this email already exists") from exc
    logger.info("user_signed_up user_id=%s", user.id)
    return user


def login(db: Session, data: LoginRequest) -> str:
    user = db.scalar(select(User).where(User.email == data.email))
    # Always run one hash verification so timing does not reveal whether the email exists.
    password_ok = verify_password(
        data.password, user.password_hash if user else DUMMY_PASSWORD_HASH
    )
    if user is None or not password_ok:
        logger.info("login_failed")
        raise UnauthorizedError("Incorrect email or password")
    logger.info("login_succeeded user_id=%s", user.id)
    return create_access_token(user.id)
