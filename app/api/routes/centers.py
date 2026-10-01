from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.dependencies import AdminUser, DbSession
from app.models.diagnostic_center import DiagnosticCenter
from app.schemas.common import error_responses
from app.schemas.diagnostic_center import (
    CenterCreate,
    CenterDetail,
    CenterRead,
    CenterTestPriceRead,
    CenterTestRead,
    PriceUpdate,
)
from app.services import catalog_service

router = APIRouter(prefix="/centers", tags=["Diagnostic centers"])

Limit = Annotated[int, Query(ge=1, le=100, description="Page size")]
Offset = Annotated[int, Query(ge=0, description="Rows to skip")]
CenterId = Annotated[int, Path(gt=0)]
TestId = Annotated[int, Path(gt=0)]


def _to_detail(center: DiagnosticCenter) -> CenterDetail:
    return CenterDetail(
        id=center.id,
        name=center.name,
        location=center.location,
        tests=[
            CenterTestRead(id=ct.test.id, name=ct.test.name, price=ct.price)
            for ct in center.center_tests
        ],
    )


@router.get("", response_model=list[CenterRead], summary="List diagnostic centers")
def list_centers(db: DbSession, limit: Limit = 50, offset: Offset = 0) -> list[CenterRead]:
    """Public endpoint. Use `GET /centers/{id}` to see the tests and prices of one center."""
    return [CenterRead.model_validate(c) for c in catalog_service.list_centers(db, limit, offset)]


@router.get(
    "/{center_id}",
    response_model=CenterDetail,
    summary="Get a center with its tests and prices",
    responses=error_responses(404),
)
def get_center(center_id: CenterId, db: DbSession) -> CenterDetail:
    return _to_detail(catalog_service.get_center(db, center_id))


@router.post(
    "",
    response_model=CenterRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a center (admin)",
    responses=error_responses(401, 403),
)
def create_center(data: CenterCreate, db: DbSession, _admin: AdminUser) -> CenterRead:
    return CenterRead.model_validate(catalog_service.create_center(db, data))


@router.put(
    "/{center_id}/tests/{test_id}",
    response_model=CenterTestPriceRead,
    summary="Offer a test at a center / change its price (admin)",
    responses={
        201: {"model": CenterTestPriceRead, "description": "Offering created"},
        **error_responses(401, 403, 404),
    },
)
def set_center_test_price(
    center_id: CenterId,
    test_id: TestId,
    data: PriceUpdate,
    response: Response,
    db: DbSession,
    _admin: AdminUser,
) -> CenterTestPriceRead:
    """Upsert the price. Existing bookings keep the price they were booked at."""
    center_test, created = catalog_service.set_price(db, center_id, test_id, data.price)
    if created:
        response.status_code = status.HTTP_201_CREATED
    return CenterTestPriceRead(
        center_id=center_test.center_id,
        test_id=center_test.test_id,
        price=center_test.price,
        updated_at=center_test.updated_at,
    )
