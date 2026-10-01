import jwt
import pytest

from app.core.config import settings
from tests.conftest import PASSWORD

SIGNUP = {"email": "New.User@Example.com", "password": PASSWORD, "full_name": "New User"}


def test_signup_success_normalizes_email_and_hides_password(client):
    resp = client.post("/auth/signup", json=SIGNUP)
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new.user@example.com"
    assert body["full_name"] == "New User"
    assert "password" not in body and "password_hash" not in body


def test_password_is_stored_hashed(client, db):
    from app.models import User

    client.post("/auth/signup", json=SIGNUP)
    stored = db.query(User).one().password_hash
    assert stored != PASSWORD and stored.startswith("$argon2")


def test_duplicate_signup_returns_409_even_with_different_case(client):
    assert client.post("/auth/signup", json=SIGNUP).status_code == 201
    resp = client.post("/auth/signup", json={**SIGNUP, "email": "NEW.USER@example.com"})
    assert resp.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {**SIGNUP, "email": "not-an-email"},
        {**SIGNUP, "password": "short1"},
        {**SIGNUP, "password": "onlyletterspassword"},
        {**SIGNUP, "password": "12345678901"},
        {**SIGNUP, "full_name": ""},
        {"email": "a@b.com"},
    ],
)
def test_signup_validation_errors(client, payload):
    assert client.post("/auth/signup", json=payload).status_code == 422


def test_login_success_returns_bearer_token(client):
    client.post("/auth/signup", json=SIGNUP)
    resp = client.post("/auth/login", json={"email": "NEW.user@example.com", "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"
    assert resp.json()["access_token"]


def test_login_wrong_password_and_unknown_user_look_identical(client):
    client.post("/auth/signup", json=SIGNUP)
    wrong = client.post("/auth/login", json={"email": SIGNUP["email"], "password": "Wrong1234"})
    unknown = client.post("/auth/login", json={"email": "no@one.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_protected_endpoint_requires_token(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


def test_protected_endpoint_rejects_garbage_and_expired_tokens(client):
    assert client.get("/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    expired = jwt.encode(
        {"sub": "1", "exp": 1}, settings.jwt_secret.get_secret_value(), algorithm="HS256"
    )
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_token_signed_with_other_secret_is_rejected(client):
    forged = jwt.encode({"sub": "1", "exp": 9999999999}, "x" * 40, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_me_returns_current_user(client, user_headers):
    resp = client.get("/auth/me", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"
