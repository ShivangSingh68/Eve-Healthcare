from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.api.dependencies import AdminUser, DbSession
from app.models.diagnostic_test import DiagnosticTest
from app.schemas.common import error_responses
from app.schemas.diagnostic_test import (
    DiagnosticTestCreate,
    DiagnosticTestDetail,
    DiagnosticTestRead,
    OfferingCenterRead,
)
from app.services import catalog_service

router = APIRouter(prefix="/tests", tags=["Diagnostic tests"])

Limit = Annotated[int, Query(ge=1, le=100, description="Page size")]
Offset = Annotated[int, Query(ge=0, description="Rows to skip")]


def _to_detail(test: DiagnosticTest) -> DiagnosticTestDetail:
    return DiagnosticTestDetail(
        id=test.id,
        name=test.name,
        description=test.description,
        centers=[
            OfferingCenterRead(
                id=ct.center.id, name=ct.center.name, location=ct.center.location, price=ct.price
            )
            for ct in test.center_tests
        ],
    )


@router.get("", response_model=list[DiagnosticTestRead], summary="List diagnostic tests")
def list_tests(db: DbSession, limit: Limit = 50, offset: Offset = 0) -> list[DiagnosticTestRead]:
    return [
        DiagnosticTestRead.model_validate(t) for t in catalog_service.list_tests(db, limit, offset)
    ]


@router.get(
    "/{test_id}",
    response_model=DiagnosticTestDetail,
    summary="Get a test with the centers that offer it",
    responses=error_responses(404),
)
def get_test(test_id: Annotated[int, Path(gt=0)], db: DbSession) -> DiagnosticTestDetail:
    return _to_detail(catalog_service.get_test(db, test_id))


@router.post(
    "",
    response_model=DiagnosticTestRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a test (admin)",
    responses=error_responses(401, 403, 409),
)
def create_test(
    data: DiagnosticTestCreate, db: DbSession, _admin: AdminUser
) -> DiagnosticTestRead:
    return DiagnosticTestRead.model_validate(catalog_service.create_test(db, data))
