from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.diagnostic_center import DiagnosticCenter
    from app.models.diagnostic_test import DiagnosticTest


class CenterTest(TimestampMixin, Base):
    """A test offered by a centre, at that centre's price (many-to-many with payload)."""

    __tablename__ = "center_tests"
    __table_args__ = (
        UniqueConstraint("center_id", "test_id", name="uq_center_tests_center_id_test_id"),
        CheckConstraint("price > 0", name="price_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    center_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_centers.id", ondelete="CASCADE"), nullable=False
    )
    test_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_tests.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    center: Mapped[DiagnosticCenter] = relationship(back_populates="center_tests")
    test: Mapped[DiagnosticTest] = relationship(back_populates="center_tests")
