"""Opt-in: `alembic upgrade head` on an empty database must equal the ORM metadata.

Set AI_MIGRATION_TEST_DSN to a DISPOSABLE, EMPTY PostgreSQL database (any SQLAlchemy
form, e.g. postgresql+asyncpg://user:pass@host:5432/scratch). The test refuses to
touch a database that already has tables, migrates it with the real Alembic CLI in a
subprocess, compares it with ``Base.metadata`` through ``alembic.autogenerate``, and
finally wipes the ``public`` schema again.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from src.bootstrap.orm import Base

BACKEND = Path(__file__).resolve().parents[2]


def _sync_url(dsn: str):
    url = make_url(dsn)
    return url.set(drivername="postgresql+psycopg2")


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE__URL": dsn}
    env.pop("DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=600,
    )


@pytest.fixture
def empty_database():
    dsn = os.getenv("AI_MIGRATION_TEST_DSN")
    if not dsn:
        pytest.skip("Set AI_MIGRATION_TEST_DSN to a disposable empty PostgreSQL database")
    engine = create_engine(_sync_url(dsn))
    with engine.connect() as connection:
        if inspect(connection).get_table_names(schema="public"):
            engine.dispose()
            pytest.skip("AI_MIGRATION_TEST_DSN database is not empty; refusing to migrate it")
    try:
        yield dsn, engine
    finally:
        # Only reached for a database that was verified empty above.
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()


def test_alembic_head_matches_orm_metadata(empty_database):
    dsn, engine = empty_database

    heads = _alembic(dsn, "heads")
    assert heads.returncode == 0, heads.stderr
    assert len([line for line in heads.stdout.splitlines() if "(head)" in line]) == 1

    upgraded = _alembic(dsn, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr[-2000:]

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": False}
        )
        diff = compare_metadata(context, Base.metadata)

    assert diff == [], f"Models and migrations diverge: {diff}"


def test_latest_migration_downgrades_and_upgrades_again(empty_database):
    dsn, _ = empty_database
    assert _alembic(dsn, "upgrade", "head").returncode == 0

    downgraded = _alembic(dsn, "downgrade", "-1")
    assert downgraded.returncode == 0, downgraded.stderr[-2000:]
    upgraded = _alembic(dsn, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr[-2000:]
