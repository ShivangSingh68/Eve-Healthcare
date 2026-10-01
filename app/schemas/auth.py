import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _check_password_strength(value: str) -> str:
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("Password must contain at least one letter and one digit")
    return value


NormalizedEmail = Annotated[EmailStr, AfterValidator(_normalize_email)]
StrongPassword = Annotated[
    str, Field(min_length=8, max_length=128), AfterValidator(_check_password_strength)
]


class SignupRequest(BaseModel):
    email: NormalizedEmail
    password: StrongPassword
    full_name: Annotated[str, Field(min_length=1, max_length=100)]


class LoginRequest(BaseModel):
    email: NormalizedEmail
    # No strength rules on login: we only compare against the stored hash.
    password: Annotated[str, Field(min_length=1, max_length=128)]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
