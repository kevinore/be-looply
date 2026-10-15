"""Section 13.1: database constraints, connected as the owner. Every insert must fail."""

from datetime import date

import pytest
from psycopg import errors

from tests.db.conftest import Base, Rows


def test_duplicate_phone_in_business(rows: Rows, base: Base):
    with pytest.raises(errors.UniqueViolation):
        rows.customer(base.business_id, "+573101234567")


def test_phone_without_country_code(rows: Rows, base: Base):
    with pytest.raises(errors.CheckViolation):
        rows.customer(base.business_id, "3101234567")


def test_second_active_welcome_spin(rows: Rows, base: Base):
    # R9
    sale_id = rows.sale(
        base.business_id, base.workday_id, base.operator_id, base.customer_id
    )
    rows.spin(base.business_id, base.customer_id, sale_id, "welcome")
    with pytest.raises(errors.UniqueViolation):
        rows.spin(base.business_id, base.customer_id, sale_id, "welcome")


def test_two_active_spins_for_same_milestone(rows: Rows, base: Base):
    # R10
    sale_id = rows.sale(
        base.business_id, base.workday_id, base.operator_id, base.customer_id
    )
    rows.spin(base.business_id, base.customer_id, sale_id, "milestone", 5)
    with pytest.raises(errors.UniqueViolation):
        rows.spin(base.business_id, base.customer_id, sale_id, "milestone", 5)


def test_two_redeemed_prizes_on_same_sale(rows: Rows, base: Base):
    # R16
    sale_id = rows.sale(
        base.business_id, base.workday_id, base.operator_id, base.customer_id
    )
    prize_id = rows.prize(base.business_id)
    spin_1 = rows.spin(base.business_id, base.customer_id, sale_id, "welcome")
    spin_2 = rows.spin(base.business_id, base.customer_id, sale_id, "milestone", 5)
    rows.redeemed_award(
        base.business_id, base.customer_id, spin_1, prize_id, sale_id, base.operator_id
    )
    with pytest.raises(errors.UniqueViolation):
        rows.redeemed_award(
            base.business_id,
            base.customer_id,
            spin_2,
            prize_id,
            sale_id,
            base.operator_id,
        )


def test_second_open_workday(rows: Rows, base: Base):
    # Different date so only workday_one_open can reject it.
    with pytest.raises(errors.UniqueViolation) as exc:
        rows.workday(base.business_id, base.operator_id, date(2026, 10, 11))
    assert exc.value.diag.constraint_name == "workday_one_open"


def test_claimed_sale_without_customer(rows: Rows, base: Base):
    with pytest.raises(errors.CheckViolation):
        rows.conn.execute(
            "INSERT INTO sale (business_id, workday_id, operator_id, status, payment_method, "
            "total_cop, idempotency_key, claim_token, claim_expires_at, claim_method, claimed_at) "
            "VALUES (%s, %s, %s, 'claimed', 'cash', 14000, gen_random_uuid(), 'tok-claimed', "
            "now(), 'qr', now())",
            (base.business_id, base.workday_id, base.operator_id),
        )


def test_void_sale_without_reason(rows: Rows, base: Base):
    with pytest.raises(errors.CheckViolation):
        rows.conn.execute(
            "INSERT INTO sale (business_id, workday_id, operator_id, status, payment_method, "
            "total_cop, idempotency_key, claim_token, claim_expires_at, voided_at, voided_by) "
            "VALUES (%s, %s, %s, 'void', 'cash', 14000, gen_random_uuid(), 'tok-void', "
            "now(), now(), %s)",
            (base.business_id, base.workday_id, base.operator_id, base.operator_id),
        )
