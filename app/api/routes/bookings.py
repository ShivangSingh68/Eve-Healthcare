from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.booking import BookingCreate, BookingRead
from app.schemas.common import error_responses
from app.services import booking_service

router = APIRouter(prefix="/bookings", tags=["Bookings"])

BookingId = Annotated[int, Path(gt=0)]


@router.post(
    "",
    response_model=BookingRead,
    status_code=status.HTTP_201_CREATED,
    summary="Book a test at a center",
    responses=error_responses(401, 404, 422),
)
def create_booking(data: BookingCreate, db: DbSession, user: CurrentUser) -> BookingRead:
    """Creates a PENDING booking. The amount is looked up server-side from the center's
    current price for that test and stored on the booking; clients cannot set it."""
    return BookingRead.model_validate(booking_service.create_booking(db, user, data))


@router.get(
    "",
    response_model=list[BookingRead],
    summary="List my bookings",
    responses=error_responses(401),
)
def list_bookings(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BookingRead]:
    return [
        BookingRead.model_validate(b)
        for b in booking_service.list_bookings(db, user, limit, offset)
    ]


@router.get(
    "/{booking_id}",
    response_model=BookingRead,
    summary="Get one of my bookings",
    responses=error_responses(401, 404),
)
def get_booking(booking_id: BookingId, db: DbSession, user: CurrentUser) -> BookingRead:
    """Another user's booking returns 404, exactly like a booking that does not exist."""
    return BookingRead.model_validate(booking_service.get_owned_booking(db, user, booking_id))


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingRead,
    summary="Cancel my booking",
    responses=error_responses(401, 404, 409),
)
def cancel_booking(booking_id: BookingId, db: DbSession, user: CurrentUser) -> BookingRead:
    """Allowed from PENDING or CONFIRMED. FAILED and CANCELLED bookings are final (409)."""
    return BookingRead.model_validate(booking_service.cancel_booking(db, user, booking_id))
