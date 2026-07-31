import os
from collections.abc import Generator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[2]


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/ingredient_lens"
    )


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    url = _database_url()
    engine = sa.create_engine(url)
    try:
        with engine.connect():
            pass
    except sa.exc.OperationalError:
        pytest.skip(f"Postgres not reachable at {url} — start it with `docker compose up -d db`")

    # Idempotent: a no-op if the schema is already at head. Each test ensures
    # its own preconditions rather than relying on other tests' ordering.
    command.upgrade(Config(str(REPO_ROOT / "alembic.ini")), "head")

    connection = engine.connect()
    transaction = connection.begin()
    # join_transaction_mode="create_savepoint": if test/application code calls
    # session.commit(), SQLAlchemy commits an inner SAVEPOINT, not the real
    # outer `transaction` -- without this, a commit() anywhere in the call
    # stack ends the real transaction early, and this fixture's rollback()
    # below becomes a no-op on an already-completed transaction, permanently
    # persisting whatever that test wrote. This is SQLAlchemy's own
    # documented fix for exactly this failure mode.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
