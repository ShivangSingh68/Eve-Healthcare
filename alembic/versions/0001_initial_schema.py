"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=100), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )

    op.create_table(
        "diagnostic_centers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diagnostic_centers")),
    )

    op.create_table(
        "diagnostic_tests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diagnostic_tests")),
        sa.UniqueConstraint("name", name=op.f("uq_diagnostic_tests_name")),
    )

    op.create_table(
        "center_tests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("center_id", sa.Integer(), nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("price > 0", name=op.f("ck_center_tests_price_positive")),
        sa.ForeignKeyConstraint(
            ["center_id"], ["diagnostic_centers.id"],
            name=op.f("fk_center_tests_center_id_diagnostic_centers"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["test_id"], ["diagnostic_tests.id"],
            name=op.f("fk_center_tests_test_id_diagnostic_tests"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_center_tests")),
        sa.UniqueConstraint("center_id", "test_id", name="uq_center_tests_center_id_test_id"),
    )

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("center_id", sa.Integer(), nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("appointment_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "CONFIRMED", "FAILED", "CANCELLED",
                    name="booking_status", native_enum=False, length=20, create_constraint=True),
            server_default="PENDING",
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint("amount > 0", name=op.f("ck_bookings_amount_positive")),
        sa.ForeignKeyConstraint(
            ["center_id", "test_id"], ["center_tests.center_id", "center_tests.test_id"],
            name="fk_bookings_center_id_test_id_center_tests", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_bookings_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookings")),
    )
    op.create_index("ix_bookings_user_id_created_at", "bookings", ["user_id", "created_at"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=128), nullable=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "status",
            sa.Enum("SUCCESS", "FAILED",
                    name="payment_status", native_enum=False, length=20, create_constraint=True),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payments_amount_positive")),
        sa.ForeignKeyConstraint(
            ["booking_id"], ["bookings.id"],
            name=op.f("fk_payments_booking_id_bookings"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("provider_payment_id", name=op.f("uq_payments_provider_payment_id")),
    )
    op.create_index("ix_payments_booking_id", "payments", ["booking_id"])
    # At most one SUCCESS payment per booking, enforced by the database.
    op.create_index(
        "uq_payments_booking_id_success", "payments", ["booking_id"],
        unique=True, postgresql_where=sa.text("status = 'SUCCESS'"),
    )

    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_webhook_events")),
        sa.UniqueConstraint("event_id", name=op.f("uq_payment_webhook_events_event_id")),
    )


def downgrade() -> None:
    op.drop_table("payment_webhook_events")
    op.drop_index("uq_payments_booking_id_success", table_name="payments")
    op.drop_index("ix_payments_booking_id", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_bookings_user_id_created_at", table_name="bookings")
    op.drop_table("bookings")
    op.drop_table("center_tests")
    op.drop_table("diagnostic_tests")
    op.drop_table("diagnostic_centers")
    op.drop_table("users")
