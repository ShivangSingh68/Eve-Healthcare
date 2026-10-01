"""Test setup.

Tests run against a REAL PostgreSQL database (TEST_DATABASE_URL), because the guarantees
under test (unique constraints, row locks, concurrent inserts) are PostgreSQL behaviour.
The schema is created by running the Alembic migrations, so the migrations are tested too.
"""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# Environment must be set BEFORE the app (and its Settings) is imported.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/eve_test"
)
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-that-is-long-enough-0123456789")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.core.security import hash_password, sign_webhook_body  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CenterTest, DiagnosticCenter, DiagnosticTest, User  # noqa: E402

PASSWORD = "Str0ngPassw0rd"
TABLES = (
    "payment_webhook_events, payments, bookings, center_tests, "
    "diagnostic_tests, diagnostic_centers, users"
)


@pytest.fixture(scope="session", autouse=True)
def _migrated_database() -> Iterator[None]:
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    yield
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


# ---------- data helpers ----------------------------------------------------------------


def future_iso(days: int = 7) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def create_user(db: Session, email: str, *, admin: bool = False) -> User:
    user = User(
        email=email, password_hash=hash_password(PASSWORD), full_name="Test User", is_admin=admin
    )
    db.add(user)
    db.commit()
    return user


def login_headers(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def signed_webhook(client: TestClient, payload: dict, *, signature: str | None = None):
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": signature if signature is not None else sign_webhook_body(body),
    }
    return client.post("/payments/webhook/", content=body, headers=headers)


@pytest.fixture
def catalog(db: Session) -> dict:
    """One centre offering one test at 500.00, plus a second centre that does not."""
    center = DiagnosticCenter(name="Apollo Diagnostics", location="Delhi")
    other_center = DiagnosticCenter(name="Empty Lab", location="Pune")
    test = DiagnosticTest(name="CBC", description="Complete blood count")
    other_test = DiagnosticTest(name="MRI", description="Not offered anywhere")
    db.add_all([center, other_center, test, other_test])
    db.flush()
    db.add(CenterTest(center_id=center.id, test_id=test.id, price=Decimal("500.00")))
    db.commit()
    return {
        "center_id": center.id,
        "other_center_id": other_center.id,
        "test_id": test.id,
        "other_test_id": other_test.id,
        "price": 500.0,
    }


@pytest.fixture
def user_headers(client: TestClient, db: Session) -> dict[str, str]:
    create_user(db, "alice@example.com")
    return login_headers(client, "alice@example.com")


@pytest.fixture
def other_headers(client: TestClient, db: Session) -> dict[str, str]:
    create_user(db, "bob@example.com")
    return login_headers(client, "bob@example.com")


@pytest.fixture
def admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    create_user(db, "admin@example.com", admin=True)
    return login_headers(client, "admin@example.com")


@pytest.fixture
def booking(client: TestClient, catalog: dict, user_headers: dict[str, str]) -> dict:
    resp = client.post(
        "/bookings",
        json={
            "center_id": catalog["center_id"],
            "test_id": catalog["test_id"],
            "appointment_at": future_iso(),
        },
        headers=user_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def webhook_payload(booking: dict, **overrides) -> dict:
    payload = {
        "event_id": "evt_1",
        "provider_payment_id": "pay_1",
        "booking_id": booking["id"],
        "status": "SUCCESS",
        "amount": booking["amount"],
    }
    payload.update(overrides)
    return payload
