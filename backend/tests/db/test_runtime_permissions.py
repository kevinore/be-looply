"""Section 13.1: app_runtime privileges (R19, R20)."""

import pytest
from psycopg import errors

from tests.db.conftest import Base

TABLES = [
    "business",
    "operator",
    "operator_session",
    "product",
    "workday",
    "customer",
    "customer_session",
    "sale",
    "prize_catalog",
    "spin",
    "prize_award",
    "sale_item",
    "event",
]


@pytest.mark.parametrize("table", TABLES)
def test_delete_denied(runtime_conn, owner_conn, table):
    with pytest.raises(errors.InsufficientPrivilege):
        runtime_conn.execute(f"DELETE FROM {table}")


def test_update_event_denied(runtime_conn, owner_conn, base: Base):
    owner_conn.execute(
        "INSERT INTO event (business_id, type, actor) VALUES (%s, 'sale_paid', 'system')",
        (base.business_id,),
    )
    owner_conn.commit()
    with pytest.raises(errors.InsufficientPrivilege):
        runtime_conn.execute("UPDATE event SET type = 'x'")


def test_create_table_denied(runtime_conn):
    with pytest.raises(errors.InsufficientPrivilege):
        runtime_conn.execute("CREATE TABLE should_not_exist (id int)")
