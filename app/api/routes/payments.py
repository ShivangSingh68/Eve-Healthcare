from fastapi import APIRouter, Depends, status

from app.api.dependencies import CurrentUser, DbSession, verify_webhook_request
from app.models.payment import Payment
from app.schemas.common import error_responses
from app.schemas.payment import PaymentCreate, PaymentRead, WebhookPayload, WebhookResponse
from app.services import payment_service, webhook_service

router = APIRouter(prefix="/payments", tags=["Payments"])


def _to_read(payment: Payment) -> PaymentRead:
    return PaymentRead(
        id=payment.id,
        booking_id=payment.booking_id,
        provider_payment_id=payment.provider_payment_id,
        amount=payment.amount,
        status=payment.status,
        booking_status=payment.booking.status,
        created_at=payment.created_at,
    )


@router.post(
    "/",
    response_model=PaymentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Pay for a booking (simulated)",
    responses=error_responses(401, 404, 409),
)
@router.post("", include_in_schema=False, response_model=PaymentRead, status_code=201)
def create_payment(data: PaymentCreate, db: DbSession, user: CurrentUser) -> PaymentRead:
    """Simulates a payment provider outcome (SUCCESS or FAILED) for one of **your** PENDING
    bookings. SUCCESS -> booking CONFIRMED, FAILED -> booking FAILED. The charged amount is
    the booking's stored amount. Paying twice returns 409."""
    return _to_read(payment_service.pay_for_booking(db, user, data.booking_id))


@router.post(
    "/webhook/",
    response_model=WebhookResponse,
    summary="Payment provider webhook (idempotent)",
    dependencies=[Depends(verify_webhook_request)],
    responses=error_responses(401, 404, 409, 422),
)
@router.post(
    "/webhook",
    include_in_schema=False,
    response_model=WebhookResponse,
    dependencies=[Depends(verify_webhook_request)],
)
def payment_webhook(payload: WebhookPayload, db: DbSession) -> WebhookResponse:
    """Called by the payment provider. Requires an `X-Webhook-Signature` header.

    * Redelivery of the same event -> 200 with `result: duplicate` (nothing changes).
    * Same `event_id` with a different body -> 409.
    * Unknown booking -> 404; amount mismatch -> 422; state-corrupting event -> 409.
    """
    return webhook_service.process_webhook(db, payload)
