from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import BookingStatus


class Booking(TimestampMixin, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        # The DB itself guarantees a booking points at a (centre, test) pair that exists
        # in center_tests, not just at two independently valid ids.
        ForeignKeyConstraint(
            ["center_id", "test_id"],
            ["center_tests.center_id", "center_tests.test_id"],
            name="fk_bookings_center_id_test_id_center_tests",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_bookings_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    center_id: Mapped[int] = mapped_column(nullable=False)
    test_id: Mapped[int] = mapped_column(nullable=False)
    appointment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Price snapshot taken at booking time; never recomputed from center_tests later.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status", native_enum=False, length=20,
             create_constraint=True),
        default=BookingStatus.PENDING,
        server_default=BookingStatus.PENDING.value,
        nullable=False,
    )
