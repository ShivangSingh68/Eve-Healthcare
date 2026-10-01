import logging
from typing import Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    UnprocessableError,
)
from app.models.booking import Booking
from app.models.center_test import CenterTest
from app.models.diagnostic_center import DiagnosticCenter
from app.models.diagnostic_test import DiagnosticTest
from app.models.enums import BookingStatus
from app.models.user import User
from app.schemas.booking import BookingCreate

logger = logging.getLogger(__name__)

# The booking state machine. Anything not listed here is rejected.
ALLOWED_TRANSITIONS: Final[dict[BookingStatus, frozenset[BookingStatus]]] = {
    BookingStatus.PENDING: frozenset(
        {BookingStatus.CONFIRMED, BookingStatus.FAILED, BookingStatus.CANCELLED}
    ),
    BookingStatus.CONFIRMED: frozenset({BookingStatus.CANCELLED}),
    BookingStatus.FAILED: frozenset(),
    BookingStatus.CANCELLED: frozenset(),
}


def transition(booking: Booking, new_status: BookingStatus) -> None:
    """Move a booking to `new_status` or raise. The ONLY place booking.status is changed."""
    if new_status not in ALLOWED_TRANSITIONS[booking.status]:
        raise InvalidStateTransitionError(
            f"Cannot change booking from {booking.status} to {new_status}"
        )
    logger.info(
        "booking_transition booking_id=%s from=%s to=%s", booking.id, booking.status, new_status
    )
    booking.status = new_status


def create_booking(db: Session, user: User, data: BookingCreate) -> Booking:
    if db.get(DiagnosticCenter, data.center_id) is None:
        raise NotFoundError("Diagnostic center not found")
    if db.get(DiagnosticTest, data.test_id) is None:
        raise NotFoundError("Diagnostic test not found")

    center_test = db.scalar(
        select(CenterTest).where(
            CenterTest.center_id == data.center_id, CenterTest.test_id == data.test_id
        )
    )
    if center_test is None:
        raise UnprocessableError("This diagnostic center does not offer the selected test")

    booking = Booking(
        user_id=user.id,
        center_id=data.center_id,
        test_id=data.test_id,
        appointment_at=data.appointment_at,
        amount=center_test.price,  # server-side price snapshot
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Could not create booking; please retry") from exc
    logger.info("booking_created booking_id=%s user_id=%s", booking.id, user.id)
    return booking


def list_bookings(db: Session, user: User, limit: int, offset: int) -> list[Booking]:
    stmt = (
        select(Booking)
        .where(Booking.user_id == user.id)
        .order_by(Booking.created_at.desc(), Booking.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))


def get_owned_booking(
    db: Session, user: User, booking_id: int, *, for_update: bool = False
) -> Booking:
    """Fetch a booking that belongs to `user`.

    Someone else's booking is reported as 404 (not 403) so IDs cannot be probed to learn
    which bookings exist. `for_update` takes a row lock for the rest of the transaction.
    """
    stmt = select(Booking).where(Booking.id == booking_id, Booking.user_id == user.id)
    if for_update:
        stmt = stmt.with_for_update()
    booking = db.scalar(stmt)
    if booking is None:
        raise NotFoundError("Booking not found")
    return booking


def cancel_booking(db: Session, user: User, booking_id: int) -> Booking:
    booking = get_owned_booking(db, user, booking_id, for_update=True)
    transition(booking, BookingStatus.CANCELLED)
    db.commit()
    return booking
