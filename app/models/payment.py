from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.booking import Booking
from app.models.enums import PaymentStatus


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        # Invariant enforced by the database: at most ONE successful payment per booking.
        Index(
            "uq_payments_booking_id_success",
            "booking_id",
            unique=True,
            postgresql_where=text("status = 'SUCCESS'"),
        ),
        Index("ix_payments_booking_id", "booking_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    # Unique when present (NULLs are allowed to repeat in PostgreSQL unique indexes).
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status", native_enum=False, length=20,
             create_constraint=True),
        nullable=False,
    )

    booking: Mapped[Booking] = relationship()
