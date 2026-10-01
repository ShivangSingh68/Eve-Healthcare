import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ConflictError, NotFoundError
from app.models.center_test import CenterTest
from app.models.diagnostic_center import DiagnosticCenter
from app.models.diagnostic_test import DiagnosticTest
from app.schemas.diagnostic_center import CenterCreate
from app.schemas.diagnostic_test import DiagnosticTestCreate

logger = logging.getLogger(__name__)


def list_centers(db: Session, limit: int, offset: int) -> list[DiagnosticCenter]:
    stmt = select(DiagnosticCenter).order_by(DiagnosticCenter.id).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def get_center(db: Session, center_id: int) -> DiagnosticCenter:
    stmt = (
        select(DiagnosticCenter)
        .where(DiagnosticCenter.id == center_id)
        .options(selectinload(DiagnosticCenter.center_tests).selectinload(CenterTest.test))
    )
    center = db.scalar(stmt)
    if center is None:
        raise NotFoundError("Diagnostic center not found")
    return center


def list_tests(db: Session, limit: int, offset: int) -> list[DiagnosticTest]:
    stmt = select(DiagnosticTest).order_by(DiagnosticTest.id).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def get_test(db: Session, test_id: int) -> DiagnosticTest:
    stmt = (
        select(DiagnosticTest)
        .where(DiagnosticTest.id == test_id)
        .options(selectinload(DiagnosticTest.center_tests).selectinload(CenterTest.center))
    )
    test = db.scalar(stmt)
    if test is None:
        raise NotFoundError("Diagnostic test not found")
    return test


def create_center(db: Session, data: CenterCreate) -> DiagnosticCenter:
    center = DiagnosticCenter(name=data.name.strip(), location=data.location.strip())
    db.add(center)
    db.commit()
    logger.info("center_created center_id=%s", center.id)
    return center


def create_test(db: Session, data: DiagnosticTestCreate) -> DiagnosticTest:
    test = DiagnosticTest(name=data.name.strip(), description=data.description)
    db.add(test)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A diagnostic test with this name already exists") from exc
    logger.info("test_created test_id=%s", test.id)
    return test


def set_price(
    db: Session, center_id: int, test_id: int, price: Decimal
) -> tuple[CenterTest, bool]:
    """Create or update the price a centre charges for a test. Returns (row, created)."""
    if db.get(DiagnosticCenter, center_id) is None:
        raise NotFoundError("Diagnostic center not found")
    if db.get(DiagnosticTest, test_id) is None:
        raise NotFoundError("Diagnostic test not found")

    center_test = db.scalar(
        select(CenterTest).where(
            CenterTest.center_id == center_id, CenterTest.test_id == test_id
        )
    )
    created = center_test is None
    if center_test is None:
        center_test = CenterTest(center_id=center_id, test_id=test_id, price=price)
        db.add(center_test)
    else:
        # Existing bookings keep their own snapshot of the old price (booking.amount).
        center_test.price = price
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Concurrent update of the same center/test price") from exc
    logger.info(
        "center_test_price_set center_id=%s test_id=%s created=%s", center_id, test_id, created
    )
    return center_test, created
