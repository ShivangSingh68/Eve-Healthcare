from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer

# Positive money with at most 2 decimal places. Serialised as a JSON number (not a string).
Money = Annotated[
    Decimal,
    Field(gt=0, max_digits=10, decimal_places=2),
    PlainSerializer(lambda v: float(v), return_type=float, when_used="json"),
]


class ErrorResponse(BaseModel):
    detail: str
    code: str


def error_responses(*status_codes: int) -> dict[int | str, dict]:
    """Helper that documents error responses in OpenAPI."""
    return {code: {"model": ErrorResponse} for code in status_codes}
