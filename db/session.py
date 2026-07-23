"""DB session handling. Hides engine/connection setup behind two entrypoints.

- get_session(): context manager for scripts (pipeline) — commits on success,
  rolls back on error, always closes.
- get_db(): generator for FastAPI's Depends() — request-scoped, no auto-commit;
  the endpoint controls its own transaction boundaries.
"""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
