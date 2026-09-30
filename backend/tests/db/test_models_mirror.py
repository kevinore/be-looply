"""10.10: every model mirrors its table exactly (names, types, nullability)."""

import pytest
from sqlalchemy.dialects import postgresql

from app.models import Base

PG_TYPE_NAMES = {
    "UUID": "uuid",
    "TEXT": "text",
    "INTEGER": "integer",
    "SMALLINT": "smallint",
    "BOOLEAN": "boolean",
    "DATE": "date",
    "JSONB": "jsonb",
    "TIMESTAMP WITH TIME ZONE": "timestamp with time zone",
}


def model_columns(table):
    dialect = postgresql.dialect()
    cols = {}
    for c in table.columns:
        compiled = c.type.compile(dialect=dialect)
        if compiled.startswith("NUMERIC"):
            type_name = "numeric" + compiled[len("NUMERIC") :].replace(" ", "")
        else:
            type_name = PG_TYPE_NAMES[compiled]
        cols[c.name] = (type_name, c.nullable)
    return cols


def db_columns(conn, table_name):
    rows = conn.execute(
        "SELECT column_name, data_type, numeric_precision, numeric_scale, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table_name,),
    ).fetchall()
    cols = {}
    for name, data_type, precision, scale, nullable in rows:
        if data_type == "numeric":
            data_type = f"numeric({precision},{scale})"
        cols[name] = (data_type, nullable == "YES")
    return cols


@pytest.mark.parametrize("table", Base.metadata.sorted_tables, ids=lambda t: t.name)
def test_model_mirrors_table(owner_conn, table):
    assert model_columns(table) == db_columns(owner_conn, table.name)


def test_every_table_has_a_model(owner_conn):
    tables = {
        name
        for (name,) in owner_conn.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
        ).fetchall()
    }
    assert tables == set(Base.metadata.tables)


@pytest.mark.parametrize("table", Base.metadata.sorted_tables, ids=lambda t: t.name)
def test_model_foreign_keys_mirror_table(owner_conn, table):
    model_fks = {
        (fk.parent.name, fk.column.table.name, fk.column.name)
        for fk in table.foreign_keys
    }
    db_fks = set(
        owner_conn.execute(
            "SELECT kcu.column_name, ccu.table_name, ccu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON kcu.constraint_name = tc.constraint_name "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON ccu.constraint_name = tc.constraint_name "
            "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = %s",
            (table.name,),
        ).fetchall()
    )
    assert model_fks == db_fks
