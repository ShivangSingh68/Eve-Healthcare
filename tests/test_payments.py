import pytest
from sqlalchemy import func, select

from app.models import Booking, BookingStatus, Payment, PaymentStatus
from app.services import payment_service


@pytest.fixture
def force_outcome(monkeypatch):
    def _set(status: PaymentStatus) -> None:
        monkeypatch.setattr(payment_service, "simulate_provider_outcome", lambda: status)

    return _set


def pay(client, booking_id, headers):
    return client.post("/payments/", json={"booking_id": booking_id}, headers=headers)


def test_successful_payment_confirms_booking(client, booking, user_headers, force_outcome, db):
    force_outcome(PaymentStatus.SUCCESS)
    resp = pay(client, booking["id"], user_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "SUCCESS"
    assert body["booking_status"] == "CONFIRMED"
    assert body["amount"] == booking["amount"]
    assert body["provider_payment_id"]

    assert client.get(f"/bookings/{booking['id']}", headers=user_headers).json()["status"] == "CONFIRMED"
    assert db.scalar(select(func.count()).select_from(Payment)) == 1


def test_failed_payment_fails_booking(client, booking, user_headers, force_outcome):
    force_outcome(PaymentStatus.FAILED)
    resp = pay(client, booking["id"], user_headers)
    assert resp.status_code == 201
    assert resp.json()["status"] == "FAILED"
    assert resp.json()["booking_status"] == "FAILED"
    assert client.get(f"/bookings/{booking['id']}", headers=user_headers).json()["status"] == "FAILED"


def test_payment_requires_authentication(client, booking):
    assert client.post("/payments/", json={"booking_id": booking["id"]}).status_code == 401


def test_payment_for_nonexistent_booking_404(client, user_headers):
    assert pay(client, 9999, user_headers).status_code == 404


def test_cannot_pay_for_someone_elses_booking(client, booking, other_headers, db, force_outcome):
    force_outcome(PaymentStatus.SUCCESS)
    assert pay(client, booking["id"], other_headers).status_code == 404
    assert db.scalar(select(func.count()).select_from(Payment)) == 0
    assert db.scalar(select(Booking.status)) == BookingStatus.PENDING


def test_duplicate_payment_rejected(client, booking, user_headers, force_outcome, db):
    force_outcome(PaymentStatus.SUCCESS)
    assert pay(client, booking["id"], user_headers).status_code == 201
    second = pay(client, booking["id"], user_headers)
    assert second.status_code == 409
    assert db.scalar(select(func.count()).select_from(Payment)) == 1


def test_cannot_pay_after_failure_or_cancellation(client, booking, user_headers, force_outcome):
    force_outcome(PaymentStatus.FAILED)
    assert pay(client, booking["id"], user_headers).status_code == 201
    assert pay(client, booking["id"], user_headers).status_code == 409


def test_cannot_pay_cancelled_booking(client, booking, user_headers, force_outcome):
    force_outcome(PaymentStatus.SUCCESS)
    client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    assert pay(client, booking["id"], user_headers).status_code == 409


def test_confirmed_booking_can_still_be_cancelled(client, booking, user_headers, force_outcome):
    force_outcome(PaymentStatus.SUCCESS)
    pay(client, booking["id"], user_headers)
    resp = client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    assert resp.status_code == 200 and resp.json()["status"] == "CANCELLED"


def test_invalid_payment_body_422(client, user_headers):
    assert client.post("/payments/", json={}, headers=user_headers).status_code == 422
    assert client.post("/payments/", json={"booking_id": "x"}, headers=user_headers).status_code == 422


def test_database_rejects_second_successful_payment_for_a_booking(booking, db):
    """Even if application code were buggy, the partial unique index protects the invariant."""
    from sqlalchemy.exc import IntegrityError

    for i in range(2):
        db.add(
            Payment(
                booking_id=booking["id"], provider_payment_id=f"p{i}",
                amount=booking["amount"], status=PaymentStatus.SUCCESS,
            )
        )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_allows_multiple_failed_payments(booking, db):
    for i in range(2):
        db.add(
            Payment(
                booking_id=booking["id"], provider_payment_id=f"f{i}",
                amount=booking["amount"], status=PaymentStatus.FAILED,
            )
        )
    db.commit()
