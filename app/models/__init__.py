"""Import every model so Base.metadata (used by Alembic) knows about all tables."""

from app.models.booking import Booking
from app.models.center_test import CenterTest
from app.models.diagnostic_center import DiagnosticCenter
from app.models.diagnostic_test import DiagnosticTest
from app.models.enums import BookingStatus, PaymentStatus
from app.models.payment import Payment
from app.models.payment_webhook_event import PaymentWebhookEvent
from app.models.user import User

__all__ = [
    "Booking",
    "BookingStatus",
    "CenterTest",
    "DiagnosticCenter",
    "DiagnosticTest",
    "Payment",
    "PaymentStatus",
    "PaymentWebhookEvent",
    "User",
]
