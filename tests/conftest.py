"""Shared fixtures. Tests that touch the DB need real Postgres (ARRAY/JSONB
columns aren't SQLite-compatible) -- point DATABASE_URL at a test instance,
e.g. the docker-compose `db` service.
"""
import pytest
from sqlalchemy import text

from db.session import SessionLocal

_STAGING_TABLES = ("ingredient_regulatory_status", "extraction_staging", "ingredients")


@pytest.fixture()
def db_session():
    session = SessionLocal()
    for table in _STAGING_TABLES:
        session.execute(text(f"TRUNCATE {table} RESTART IDENTITY CASCADE"))
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        for table in _STAGING_TABLES:
            session.execute(text(f"TRUNCATE {table} RESTART IDENTITY CASCADE"))
        session.commit()
        session.close()
