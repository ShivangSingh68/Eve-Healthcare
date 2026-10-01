import pytest
from sqlalchemy import select

from app.models import Booking, BookingStatus
from app.services.booking_service import ALLOWED_TRANSITIONS, transition
from tests.conftest import future_iso


def payload(catalog, **overrides):
    body = {
        "center_id": catalog["center_id"],
        "test_id": catalog["test_id"],
        "appointment_at": future_iso(),
    }
    body.update(overrides)
    return body


def test_create_booking_success(client, catalog, user_headers):
    resp = client.post("/bookings", json=payload(catalog), headers=user_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "PENDING"
    assert body["amount"] == 500.0
    assert body["center_id"] == catalog["center_id"]


def test_booking_requires_authentication(client, catalog):
    assert client.post("/bookings", json=payload(catalog)).status_code == 401
    assert client.get("/bookings").status_code == 401
    assert client.get("/bookings/1").status_code == 401
    assert client.post("/bookings/1/cancel").status_code == 401


def test_nonexistent_center_404(client, catalog, user_headers):
    resp = client.post("/bookings", json=payload(catalog, center_id=9999), headers=user_headers)
    assert resp.status_code == 404


def test_nonexistent_test_404(client, catalog, user_headers):
    resp = client.post("/bookings", json=payload(catalog, test_id=9999), headers=user_headers)
    assert resp.status_code == 404


def test_test_not_offered_by_center_422(client, catalog, user_headers):
    by_other_center = client.post(
        "/bookings", json=payload(catalog, center_id=catalog["other_center_id"]), headers=user_headers
    )
    unoffered_test = client.post(
        "/bookings", json=payload(catalog, test_id=catalog["other_test_id"]), headers=user_headers
    )
    assert by_other_center.status_code == unoffered_test.status_code == 422


def test_amount_is_decided_by_server_and_client_value_is_ignored(client, catalog, user_headers):
    resp = client.post(
        "/bookings", json=payload(catalog, amount=1), headers=user_headers
    )
    assert resp.status_code == 201
    assert resp.json()["amount"] == 500.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"appointment_at": "2020-01-01T10:00:00Z"},  # past
        {"appointment_at": "2099-01-01T10:00:00"},  # no timezone
        {"appointment_at": "not-a-date"},
        {"center_id": 0},
        {"center_id": "abc"},
    ],
)
def test_invalid_booking_payload_422(client, catalog, user_headers, overrides):
    resp = client.post("/bookings", json=payload(catalog, **overrides), headers=user_headers)
    assert resp.status_code == 422


def test_missing_fields_422(client, user_headers):
    assert client.post("/bookings", json={}, headers=user_headers).status_code == 422


def test_historical_price_is_preserved_when_center_changes_price(
    client, catalog, user_headers, admin_headers, booking
):
    url = f"/centers/{catalog['center_id']}/tests/{catalog['test_id']}"
    assert client.put(url, json={"price": 900}, headers=admin_headers).status_code == 200

    old = client.get(f"/bookings/{booking['id']}", headers=user_headers).json()
    new = client.post("/bookings", json=payload(catalog), headers=user_headers).json()
    assert old["amount"] == 500.0
    assert new["amount"] == 900.0


def test_user_only_sees_own_bookings(client, booking, user_headers, other_headers):
    mine = client.get("/bookings", headers=user_headers).json()
    theirs = client.get("/bookings", headers=other_headers).json()
    assert [b["id"] for b in mine] == [booking["id"]]
    assert theirs == []


def test_other_users_booking_is_404_not_leaked(client, booking, other_headers):
    url = f"/bookings/{booking['id']}"
    assert client.get(url, headers=other_headers).status_code == 404
    assert client.post(f"{url}/cancel", headers=other_headers).status_code == 404


def test_get_unknown_booking_404(client, user_headers):
    assert client.get("/bookings/9999", headers=user_headers).status_code == 404
    assert client.get("/bookings/abc", headers=user_headers).status_code == 422


def test_cancel_pending_booking(client, booking, user_headers):
    resp = client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"


def test_cancel_twice_is_invalid_transition(client, booking, user_headers):
    url = f"/bookings/{booking['id']}/cancel"
    assert client.post(url, headers=user_headers).status_code == 200
    resp = client.post(url, headers=user_headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "invalid_state_transition"


def test_cancel_failed_booking_is_rejected(client, db, booking, user_headers):
    db.execute(select(Booking))  # make sure the session is usable
    db.query(Booking).update({"status": BookingStatus.FAILED})
    db.commit()
    resp = client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    assert resp.status_code == 409


# ---- state machine unit tests (no DB) ---------------------------------------------------

VALID = [
    (BookingStatus.PENDING, BookingStatus.CONFIRMED),
    (BookingStatus.PENDING, BookingStatus.FAILED),
    (BookingStatus.PENDING, BookingStatus.CANCELLED),
    (BookingStatus.CONFIRMED, BookingStatus.CANCELLED),
]
INVALID = [
    (a, b)
    for a in BookingStatus
    for b in BookingStatus
    if (a, b) not in VALID
]


@pytest.mark.parametrize(("src", "dst"), VALID)
def test_valid_transitions(src, dst):
    b = Booking(status=src)
    transition(b, dst)
    assert b.status == dst


@pytest.mark.parametrize(("src", "dst"), INVALID)
def test_invalid_transitions(src, dst):
    from app.core.exceptions import InvalidStateTransitionError

    b = Booking(status=src)
    with pytest.raises(InvalidStateTransitionError):
        transition(b, dst)
    assert b.status == src


def test_terminal_states_have_no_exits():
    assert ALLOWED_TRANSITIONS[BookingStatus.FAILED] == frozenset()
    assert ALLOWED_TRANSITIONS[BookingStatus.CANCELLED] == frozenset()
