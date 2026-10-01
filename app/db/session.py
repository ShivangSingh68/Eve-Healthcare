from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)

# expire_on_commit=False lets us return ORM objects after commit without re-querying.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """One session per request. Services commit explicitly; anything uncommitted is
    rolled back when the session closes (including when an exception propagates)."""
    with SessionLocal() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
