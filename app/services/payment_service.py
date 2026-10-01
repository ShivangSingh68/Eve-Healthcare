import logging
import random
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError
from app.models.enums import BookingStatus, PaymentStatus
from app.models.payment import Payment
from app.models.user import User
from app.services import booking_service

logger = logging.getLogger(__name__)


def simulate_provider_outcome() -> PaymentStatus:
    """Stand-in for a real payment provider. Tests monkeypatch this for determinism."""
    if random.random() < settings.payment_success_rate:
        return PaymentStatus.SUCCESS
    return PaymentStatus.FAILED


def pay_for_booking(db: Session, user: User, booking_id: int) -> Payment:
    # Row lock: two simultaneous payment attempts for one booking are serialised, so the
    # second one sees the updated status and is rejected.
    booking = booking_service.get_owned_booking(db, user, booking_id, for_update=True)

    if booking.status != BookingStatus.PENDING:
        raise ConflictError(f"Booking is {booking.status}; only PENDING bookings can be paid")

    outcome = simulate_provider_outcome()
    payment = Payment(
        booking=booking,
        provider_payment_id=f"sim_{uuid.uuid4().hex}",
        amount=booking.amount,  # always the stored snapshot, never client input
        status=outcome,
    )
    db.add(payment)
    booking_service.transition(
        booking,
        BookingStatus.CONFIRMED if outcome == PaymentStatus.SUCCESS else BookingStatus.FAILED,
    )

    try:
        db.commit()  # payment row + booking status change succeed or fail together
    except IntegrityError as exc:
        db.rollback()
        logger.exception("payment_commit_failed booking_id=%s", booking_id)
        raise ConflictError("Payment conflicts with an existing payment") from exc

    if outcome == PaymentStatus.FAILED:
        logger.warning("payment_failed booking_id=%s payment_id=%s", booking_id, payment.id)
    else:
        logger.info("payment_succeeded booking_id=%s payment_id=%s", booking_id, payment.id)
    return payment
