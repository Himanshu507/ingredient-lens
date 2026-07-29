import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "ingredients",
    "ingredient_versions",
    "manufacturers",
    "manufacturer_versions",
    "products",
    "product_versions",
    "product_ingredients",
    "warnings",
    "recalls",
    "aliases",
    "references",
    "sources",
    "ingestion_logs",
    "entity_resolution_reviews",
}


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/ingredient_lens"
    )


def test_upgrade_head_creates_expected_schema() -> None:
    """Encodes ROADMAP.md Brick 2's done-when: `alembic upgrade head` runs cleanly
    against a fresh database and produces the tables DATABASE_DESIGN.md specifies.
    """
    url = _database_url()
    engine = sa.create_engine(url)
    try:
        with engine.connect():
            pass
    except sa.exc.OperationalError:
        pytest.skip(f"Postgres not reachable at {url} — start it with `docker compose up -d db`")

    alembic_config = Config(str(REPO_ROOT / "alembic.ini"))

    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    try:
        inspector = sa.inspect(engine)
        tables = set(inspector.get_table_names())
        assert EXPECTED_TABLES <= tables

        current_version_fks = {
            "ingredients": "ingredient_versions",
            "manufacturers": "manufacturer_versions",
            "products": "product_versions",
        }
        for table, version_table in current_version_fks.items():
            fk_targets = {fk["referred_table"] for fk in inspector.get_foreign_keys(table)}
            assert version_table in fk_targets, (
                f"{table}.current_version_id should have a FK into {version_table}"
            )
    finally:
        command.downgrade(alembic_config, "base")
