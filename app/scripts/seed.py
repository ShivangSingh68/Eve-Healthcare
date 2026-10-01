"""Seed sample data and (optionally) an admin user. Safe to run repeatedly.

    python -m app.scripts.seed

Set ADMIN_EMAIL and ADMIN_PASSWORD in the environment to create an admin account.
"""

import logging
from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import CenterTest, DiagnosticCenter, DiagnosticTest, User

logger = logging.getLogger(__name__)

TESTS = {
    "CBC": "Complete blood count",
    "Lipid Profile": "Cholesterol and triglycerides panel",
    "HbA1c": "Three-month average blood sugar",
}
CENTERS = {
    "Apollo Diagnostics": ("Delhi", {"CBC": "500.00", "Lipid Profile": "800.00"}),
    "LifeCare Labs": ("Mumbai", {"CBC": "450.00", "HbA1c": "650.00"}),
}


def seed() -> None:
    with SessionLocal() as db:
        tests = {}
        for name, description in TESTS.items():
            test = db.scalar(select(DiagnosticTest).where(DiagnosticTest.name == name))
            if test is None:
                test = DiagnosticTest(name=name, description=description)
                db.add(test)
            tests[name] = test
        db.flush()

        for name, (location, offerings) in CENTERS.items():
            center = db.scalar(select(DiagnosticCenter).where(DiagnosticCenter.name == name))
            if center is None:
                center = DiagnosticCenter(name=name, location=location)
                db.add(center)
                db.flush()
                for test_name, price in offerings.items():
                    db.add(
                        CenterTest(
                            center_id=center.id,
                            test_id=tests[test_name].id,
                            price=Decimal(price),
                        )
                    )

        if settings.admin_email and settings.admin_password:
            email = settings.admin_email.strip().lower()
            if db.scalar(select(User).where(User.email == email)) is None:
                db.add(
                    User(
                        email=email,
                        password_hash=hash_password(settings.admin_password.get_secret_value()),
                        full_name="Admin",
                        is_admin=True,
                    )
                )
                logger.info("admin_created email=%s", email)
        db.commit()
    logger.info("seed_complete")


if __name__ == "__main__":
    configure_logging(settings.log_level)
    seed()
