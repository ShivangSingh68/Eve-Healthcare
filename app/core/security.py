"""Password hashing, JWT handling and webhook signature verification."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import settings
from app.core.exceptions import UnauthorizedError

_hasher = PasswordHasher()  # Argon2id with library defaults

# Verified against when the email is unknown, so "no such user" and "wrong password"
# take about the same time (mitigates user enumeration through timing).
DUMMY_PASSWORD_HASH = _hasher.hash("not-a-real-password")


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> int:
    """Return the user id in the token or raise UnauthorizedError."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
        return int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise UnauthorizedError("Invalid or expired token") from exc


def sign_webhook_body(body: bytes) -> str:
    """HMAC-SHA256 hex digest of the raw request body (what the provider would send)."""
    secret = settings.webhook_secret.get_secret_value().encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify_webhook_signature(body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(sign_webhook_body(body), signature.strip().lower())
