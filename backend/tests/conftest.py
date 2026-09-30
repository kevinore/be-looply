import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

# Local database from docker-compose.test.yml (never Neon).
OWNER_URL = "postgresql://owner:owner@localhost:5433/app_test"
RUNTIME_URL = "postgresql://app_runtime:runtime@localhost:5433/app_test"

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def migrated_db() -> None:
    os.environ["MIGRATION_DATABASE_URL"] = OWNER_URL
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")


def truncate_all(conn: psycopg.Connection) -> None:
    tables = conn.execute(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
    ).fetchall()
    conn.execute("TRUNCATE " + ", ".join(t for (t,) in tables) + " CASCADE")
    conn.commit()


@pytest.fixture
def owner_conn(migrated_db):
    with psycopg.connect(OWNER_URL) as conn:
        truncate_all(conn)
        yield conn


@pytest.fixture
def runtime_conn(migrated_db):
    with psycopg.connect(RUNTIME_URL) as conn:
        yield conn
