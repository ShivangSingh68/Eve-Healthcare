from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Money


class CenterCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    location: Annotated[str, Field(min_length=1, max_length=200)]


class CenterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: str


class CenterTestRead(BaseModel):
    """A test as offered by one centre (includes that centre's price)."""

    id: int
    name: str
    price: Money


class CenterDetail(CenterRead):
    tests: list[CenterTestRead]


class PriceUpdate(BaseModel):
    price: Money


class CenterTestPriceRead(BaseModel):
    center_id: int
    test_id: int
    price: Money
    updated_at: datetime
