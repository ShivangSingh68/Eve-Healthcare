"""Idempotent processing of payment-provider webhook events.

Idempotency relies on the database, not on application-level "if exists" checks:

1. We INSERT a row into payment_webhook_events first. UNIQUE(event_id) means only one
   transaction can ever succeed for a given event_id. Under concurrency PostgreSQL makes
   the second inserter wait for the first to finish, then fail with a unique violation.
2. The booking row is locked (SELECT ... FOR UPDATE) before its state is evaluated.
3. Event row + payment row + booking update are committed in ONE transaction. If the event
   is rejected (404/409/422) the whole transaction rolls back, including the event row, so
   a corrected redelivery can still be processed later.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ConflictError, NotFoundError, UnprocessableError
from app.models.booking import Booking
from app.models.enums import BookingStatus, PaymentStatus
from app.models.payment import Payment
from app.models.payment_webhook_event import PaymentWebhookEvent
from app.schemas.payment import WebhookPayload, WebhookResponse
from app.services import booking_service

logger = logging.getLogger(__name__)

Result = Literal["processed", "duplicate", "ignored"]


def _hash_payload(payload_json: dict) -> str:
    canonical = json.dumps(payload_json, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def process_webhook(db: Session, payload: WebhookPayload) -> WebhookResponse:
    payload_json = payload.model_dump(mode="json")
    payload_hash = _hash_payload(payload_json)

    event = PaymentWebhookEvent(
        event_id=payload.event_id,
        provider_payment_id=payload.provider_payment_id,
        payload=payload_json,
        payload_hash=payload_hash,
    )
    db.add(event)
    try:
        db.flush()  # claims the event_id; blocks if another transaction holds it
    except IntegrityError:
        db.rollback()
        return _handle_redelivery(db, payload, payload_hash)

    try:
        result = _apply_event(db, payload)
        event.processed_at = datetime.now(UTC)
        db.commit()
    except AppError as exc:
        db.rollback()
        logger.warning(
            "webhook_rejected event_id=%s booking_id=%s reason=%s",
            payload.event_id, payload.booking_id, exc.detail,
        )
        raise
    except IntegrityError as exc:
        # e.g. provider_payment_id already used by another booking (race between events)
        db.rollback()
        logger.warning(
            "webhook_rejected event_id=%s booking_id=%s reason=integrity_error",
            payload.event_id, payload.booking_id,
        )
        raise ConflictError("Event conflicts with an existing payment record") from exc
    except Exception:
        db.rollback()
        logger.exception("webhook_failed event_id=%s", payload.event_id)
        raise

    logger.info(
        "webhook_processed event_id=%s booking_id=%s status=%s result=%s",
        payload.event_id, payload.booking_id, payload.status, result,
    )
    return WebhookResponse(
        event_id=payload.event_id, booking_id=payload.booking_id, result=result
    )


def _handle_redelivery(
    db: Session, payload: WebhookPayload, payload_hash: str
) -> WebhookResponse:
    existing = db.scalar(
        select(PaymentWebhookEvent).where(PaymentWebhookEvent.event_id == payload.event_id)
    )
    if existing is None:  # cannot normally happen: a unique violation means it exists
        raise ConflictError("Event could not be recorded; please retry")
    if existing.payload_hash != payload_hash:
        logger.warning("webhook_event_id_reused event_id=%s", payload.event_id)
        raise ConflictError("event_id was already used with a different payload")
    logger.info("webhook_duplicate event_id=%s", payload.event_id)
    return WebhookResponse(
        event_id=payload.event_id, booking_id=payload.booking_id, result="duplicate"
    )


def _apply_event(db: Session, payload: WebhookPayload) -> Result:
    booking = db.scalar(
        select(Booking).where(Booking.id == payload.booking_id).with_for_update()
    )
    if booking is None:
        raise NotFoundError("Booking not found")

    if payload.amount != booking.amount:
        raise UnprocessableError("Webhook amount does not match the booking amount")

    existing = db.scalar(
        select(Payment).where(Payment.provider_payment_id == payload.provider_payment_id)
    )
    if existing is not None and existing.booking_id != booking.id:
        raise ConflictError("provider_payment_id belongs to a different booking")

    if booking.status == BookingStatus.PENDING:
        db.add(
            Payment(
                booking=booking,
                provider_payment_id=payload.provider_payment_id,
                amount=booking.amount,
                status=payload.status,
            )
        )
        booking_service.transition(
            booking,
            BookingStatus.CONFIRMED
            if payload.status == PaymentStatus.SUCCESS
            else BookingStatus.FAILED,
        )
        db.flush()
        return "processed"

    # Booking already left PENDING. The same provider payment reported again under a new
    # event_id with the same outcome is harmless -> acknowledge without changing anything.
    if existing is not None and existing.status == payload.status:
        return "ignored"

    # Everything else would corrupt state: SUCCESS after FAILED, FAILED after SUCCESS,
    # a second *different* successful payment, or any payment on a cancelled booking.
    raise ConflictError(
        f"Booking is {booking.status}; cannot apply a {payload.status} payment event"
    )
