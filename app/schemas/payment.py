from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.models.enums import BookingStatus, PaymentStatus
from app.schemas.common import Money

PositiveInt = Annotated[int, Field(gt=0)]


class PaymentCreate(BaseModel):
    booking_id: PositiveInt


class PaymentRead(BaseModel):
    id: int
    booking_id: int
    provider_payment_id: str | None
    amount: Money
    status: PaymentStatus
    booking_status: BookingStatus
    created_at: datetime


class WebhookPayload(BaseModel):
    event_id: Annotated[str, Field(min_length=1, max_length=128)]
    provider_payment_id: Annotated[str, Field(min_length=1, max_length=128)]
    booking_id: PositiveInt
    status: PaymentStatus  # anything other than SUCCESS / FAILED -> 422
    amount: Money


class WebhookResponse(BaseModel):
    event_id: str
    booking_id: int
    result: Literal["processed", "duplicate", "ignored"]
