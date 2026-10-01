import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import Booking, BookingStatus, Payment, PaymentStatus, PaymentWebhookEvent
from tests.conftest import signed_webhook, webhook_payload


def count(db, model) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


def booking_status(db, booking_id: int) -> BookingStatus:
    db.expire_all()
    return db.get(Booking, booking_id).status


# ---- signature -------------------------------------------------------------------------


def test_missing_or_bad_signature_is_401(client, booking):
    payload = webhook_payload(booking)
    assert client.post("/payments/webhook/", json=payload).status_code == 401
    assert signed_webhook(client, payload, signature="deadbeef").status_code == 401


def test_signature_is_checked_before_payload_validation(client):
    assert client.post("/payments/webhook/", json={"garbage": True}).status_code == 401


# ---- happy paths -----------------------------------------------------------------------


def test_success_webhook_confirms_booking(client, db, booking):
    resp = signed_webhook(client, webhook_payload(booking))
    assert resp.status_code == 200
    assert resp.json() == {"event_id": "evt_1", "booking_id": booking["id"], "result": "processed"}
    assert booking_status(db, booking["id"]) == BookingStatus.CONFIRMED
    payment = db.scalar(select(Payment))
    assert payment.status == PaymentStatus.SUCCESS and payment.provider_payment_id == "pay_1"
    assert count(db, PaymentWebhookEvent) == 1
    assert db.scalar(select(PaymentWebhookEvent.processed_at)) is not None


def test_failed_webhook_fails_booking(client, db, booking):
    resp = signed_webhook(client, webhook_payload(booking, status="FAILED"))
    assert resp.status_code == 200
    assert booking_status(db, booking["id"]) == BookingStatus.FAILED
    assert db.scalar(select(Payment.status)) == PaymentStatus.FAILED


def test_webhook_works_without_trailing_slash(client, booking):
    import json

    from app.core.security import sign_webhook_body

    body = json.dumps(webhook_payload(booking)).encode()
    resp = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Webhook-Signature": sign_webhook_body(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200


# ---- idempotency -----------------------------------------------------------------------


def test_duplicate_event_is_acknowledged_without_side_effects(client, db, booking):
    payload = webhook_payload(booking)
    first = signed_webhook(client, payload)
    second = signed_webhook(client, payload)
    third = signed_webhook(client, payload)

    assert [r.status_code for r in (first, second, third)] == [200, 200, 200]
    assert first.json()["result"] == "processed"
    assert second.json()["result"] == third.json()["result"] == "duplicate"
    assert count(db, Payment) == 1
    assert count(db, PaymentWebhookEvent) == 1
    assert booking_status(db, booking["id"]) == BookingStatus.CONFIRMED


def test_duplicate_failed_event_is_idempotent(client, db, booking):
    payload = webhook_payload(booking, status="FAILED")
    signed_webhook(client, payload)
    assert signed_webhook(client, payload).json()["result"] == "duplicate"
    assert count(db, Payment) == 1


def test_same_event_id_with_different_payload_conflicts(client, db, booking):
    signed_webhook(client, webhook_payload(booking))
    resp = signed_webhook(client, webhook_payload(booking, status="FAILED"))
    assert resp.status_code == 409
    assert booking_status(db, booking["id"]) == BookingStatus.CONFIRMED
    assert count(db, Payment) == 1


def test_concurrent_identical_webhooks_create_exactly_one_payment(db, booking):
    """Fire the same event from many threads at once; the DB constraint must serialise them."""
    n = 8
    payload = webhook_payload(booking, event_id="evt_race")
    barrier = threading.Barrier(n)
    results: list = [None] * n

    def worker(i: int) -> None:
        with TestClient(app) as c:
            barrier.wait()
            r = signed_webhook(c, payload)
            results[i] = (r.status_code, r.json().get("result"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(code == 200 for code, _ in results), results
    outcomes = sorted(result for _, result in results)
    assert outcomes.count("processed") == 1
    assert outcomes.count("duplicate") == n - 1
    assert count(db, Payment) == 1
    assert count(db, PaymentWebhookEvent) == 1
    assert booking_status(db, booking["id"]) == BookingStatus.CONFIRMED


def test_concurrent_different_events_for_same_booking_confirm_once(db, booking):
    """Two *different* success events race for one booking: exactly one may win."""
    n = 6
    barrier = threading.Barrier(n)
    codes: list = [None] * n

    def worker(i: int) -> None:
        payload = webhook_payload(booking, event_id=f"evt_{i}", provider_payment_id=f"pay_{i}")
        with TestClient(app) as c:
            barrier.wait()
            codes[i] = signed_webhook(c, payload).status_code

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(codes) == [200] + [409] * (n - 1), codes
    assert count(db, Payment) == 1
    assert count(db, PaymentWebhookEvent) == 1  # rejected events were rolled back


# ---- validation & rejected events ------------------------------------------------------


def test_nonexistent_booking_404_and_event_not_recorded(client, db, booking):
    resp = signed_webhook(client, webhook_payload(booking, booking_id=9999))
    assert resp.status_code == 404
    assert count(db, PaymentWebhookEvent) == 0


def test_amount_mismatch_422_and_nothing_changes(client, db, booking):
    resp = signed_webhook(client, webhook_payload(booking, amount=1))
    assert resp.status_code == 422
    assert booking_status(db, booking["id"]) == BookingStatus.PENDING
    assert count(db, Payment) == 0 and count(db, PaymentWebhookEvent) == 0


def test_rejected_event_can_be_redelivered_after_it_becomes_valid(client, db, booking):
    bad = webhook_payload(booking, amount=1)
    assert signed_webhook(client, bad).status_code == 422
    good = webhook_payload(booking)  # same event_id, corrected amount
    assert signed_webhook(client, good).status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "REFUNDED"},
        {"status": "success"},
        {"amount": -5},
        {"amount": 0},
        {"amount": "abc"},
        {"event_id": ""},
        {"provider_payment_id": ""},
        {"booking_id": "x"},
        {"booking_id": 0},
    ],
)
def test_invalid_payload_422(client, booking, overrides):
    assert signed_webhook(client, webhook_payload(booking, **overrides)).status_code == 422


def test_missing_fields_422(client):
    assert signed_webhook(client, {"event_id": "evt"}).status_code == 422


# ---- state-conflict rules --------------------------------------------------------------


def test_success_after_failed_is_rejected(client, db, booking):
    signed_webhook(client, webhook_payload(booking, status="FAILED"))
    resp = signed_webhook(
        client, webhook_payload(booking, event_id="evt_2", provider_payment_id="pay_2")
    )
    assert resp.status_code == 409
    assert booking_status(db, booking["id"]) == BookingStatus.FAILED
    assert count(db, Payment) == 1


def test_failed_after_success_is_rejected(client, db, booking):
    signed_webhook(client, webhook_payload(booking))
    resp = signed_webhook(
        client,
        webhook_payload(booking, event_id="evt_2", provider_payment_id="pay_2", status="FAILED"),
    )
    assert resp.status_code == 409
    assert booking_status(db, booking["id"]) == BookingStatus.CONFIRMED


def test_second_different_success_payment_is_rejected(client, db, booking):
    signed_webhook(client, webhook_payload(booking))
    resp = signed_webhook(
        client, webhook_payload(booking, event_id="evt_2", provider_payment_id="pay_2")
    )
    assert resp.status_code == 409
    assert count(db, Payment) == 1


def test_same_payment_reported_under_new_event_id_is_ignored(client, db, booking):
    signed_webhook(client, webhook_payload(booking))
    resp = signed_webhook(client, webhook_payload(booking, event_id="evt_other"))
    assert resp.status_code == 200
    assert resp.json()["result"] == "ignored"
    assert count(db, Payment) == 1
    assert count(db, PaymentWebhookEvent) == 2


def test_failed_twice_with_new_event_id_is_ignored(client, db, booking):
    signed_webhook(client, webhook_payload(booking, status="FAILED"))
    resp = signed_webhook(client, webhook_payload(booking, event_id="evt_2", status="FAILED"))
    assert resp.status_code == 200 and resp.json()["result"] == "ignored"
    assert count(db, Payment) == 1


def test_payment_for_cancelled_booking_is_rejected(client, db, booking, user_headers):
    client.post(f"/bookings/{booking['id']}/cancel", headers=user_headers)
    resp = signed_webhook(client, webhook_payload(booking))
    assert resp.status_code == 409
    assert booking_status(db, booking["id"]) == BookingStatus.CANCELLED
    assert count(db, Payment) == 0


def test_provider_payment_id_cannot_be_shared_between_bookings(
    client, db, catalog, booking, user_headers
):
    from tests.conftest import future_iso

    second = client.post(
        "/bookings",
        json={
            "center_id": catalog["center_id"],
            "test_id": catalog["test_id"],
            "appointment_at": future_iso(10),
        },
        headers=user_headers,
    ).json()
    assert signed_webhook(client, webhook_payload(booking)).status_code == 200
    resp = signed_webhook(client, webhook_payload(second, event_id="evt_2"))  # same pay_1
    assert resp.status_code == 409
    assert booking_status(db, second["id"]) == BookingStatus.PENDING


def test_webhook_after_simulated_payment_is_rejected_as_duplicate_success(
    client, db, booking, user_headers, monkeypatch
):
    from app.services import payment_service

    monkeypatch.setattr(
        payment_service, "simulate_provider_outcome", lambda: PaymentStatus.SUCCESS
    )
    client.post("/payments/", json={"booking_id": booking["id"]}, headers=user_headers)
    resp = signed_webhook(client, webhook_payload(booking))
    assert resp.status_code == 409
    assert count(db, Payment) == 1
