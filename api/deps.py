import os
from collections.abc import Iterator

from sqlalchemy.orm import Session, sessionmaker

from database.session import make_session_factory

_session_factory: sessionmaker[Session] | None = None


def _get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(os.environ["DATABASE_URL"])
    return _session_factory


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped Session.

    Lazily creates the engine/session factory on first use, not at import
    time — routes/tests that don't touch the database never need
    `DATABASE_URL` set (see api/main.py's `/` and `/health`, Brick 4).
    """
    session = _get_session_factory()()
    try:
        yield session
    finally:
        session.close()
