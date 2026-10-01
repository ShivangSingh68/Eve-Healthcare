from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import BookingStatus
from app.schemas.common import Money

PositiveInt = Annotated[int, Field(gt=0)]


class BookingCreate(BaseModel):
    # NOTE: there is intentionally no `amount` field. The server decides the price.
    center_id: PositiveInt
    test_id: PositiveInt
    appointment_at: datetime

    @field_validator("appointment_at")
    @classmethod
    def _must_be_future_and_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("appointment_at must include a timezone (e.g. ...Z)")
        if v <= datetime.now(UTC):
            raise ValueError("appointment_at must be in the future")
        return v


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    center_id: int
    test_id: int
    appointment_at: datetime
    amount: Money
    status: BookingStatus
    created_at: datetime
    updated_at: datetime
