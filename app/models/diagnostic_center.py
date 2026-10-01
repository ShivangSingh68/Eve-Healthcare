from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.center_test import CenterTest


class DiagnosticCenter(TimestampMixin, Base):
    __tablename__ = "diagnostic_centers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)

    center_tests: Mapped[list[CenterTest]] = relationship(
        back_populates="center", order_by="CenterTest.id"
    )
