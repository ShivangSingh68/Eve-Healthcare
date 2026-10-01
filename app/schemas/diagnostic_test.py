from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Money


class DiagnosticTestCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(max_length=2000)] | None = None


class DiagnosticTestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None


class OfferingCenterRead(BaseModel):
    """A centre offering a test (includes that centre's price)."""

    id: int
    name: str
    location: str
    price: Money


class DiagnosticTestDetail(DiagnosticTestRead):
    centers: list[OfferingCenterRead]
