from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest


@dataclass
class Rows:
    """Minimal rows for database-level tests, inserted as the owner."""

    conn: psycopg.Connection

    def one(self, sql: str, *params) -> UUID:
        return self.conn.execute(sql, params).fetchone()[0]

    def business(self) -> UUID:
        return self.one(
            "INSERT INTO business (slug, name) VALUES (%s, 'Test') RETURNING id",
            f"biz-{uuid4().hex[:8]}",
        )

    def operator(self, business_id: UUID) -> UUID:
        return self.one(
            "INSERT INTO operator (business_id, email, name, password_hash, role) "
            "VALUES (%s, %s, 'Op', 'x', 'owner') RETURNING id",
            business_id,
            f"op-{uuid4().hex[:8]}@test.local",
        )

    def workday(
        self, business_id: UUID, operator_id: UUID, local_date: date = date(2026, 10, 4)
    ) -> UUID:
        return self.one(
            "INSERT INTO workday (business_id, local_date, day_type, opened_by) "
            "VALUES (%s, %s, 'sunday', %s) RETURNING id",
            business_id,
            local_date,
            operator_id,
        )

    def customer(self, business_id: UUID, phone: str = "+573101234567") -> UUID:
        return self.one(
            "INSERT INTO customer (business_id, phone, alias, consent_at, consent_version) "
            "VALUES (%s, %s, 'Ana', now(), 'v1') RETURNING id",
            business_id,
            phone,
        )

    def sale(
        self,
        business_id: UUID,
        workday_id: UUID,
        operator_id: UUID,
        customer_id: UUID | None = None,
    ) -> UUID:
        if customer_id is None:
            return self.one(
                "INSERT INTO sale (business_id, workday_id, operator_id, status, "
                "payment_method, total_cop, idempotency_key, claim_token, claim_expires_at) "
                "VALUES (%s, %s, %s, 'paid', 'cash', 14000, %s, %s, now() + interval '1 hour') "
                "RETURNING id",
                business_id,
                workday_id,
                operator_id,
                uuid4(),
                uuid4().hex,
            )
        return self.one(
            "INSERT INTO sale (business_id, workday_id, operator_id, customer_id, status, "
            "payment_method, total_cop, idempotency_key, claim_token, claim_expires_at, "
            "claim_method, claimed_at) "
            "VALUES (%s, %s, %s, %s, 'claimed', 'cash', 14000, %s, %s, "
            "now() + interval '1 hour', 'qr', now()) RETURNING id",
            business_id,
            workday_id,
            operator_id,
            customer_id,
            uuid4(),
            uuid4().hex,
        )

    def spin(
        self,
        business_id: UUID,
        customer_id: UUID,
        sale_id: UUID,
        reason: str = "welcome",
        milestone_n: int | None = None,
    ) -> UUID:
        return self.one(
            "INSERT INTO spin (business_id, customer_id, reason, milestone_n, "
            "unlocked_by_sale_id) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            business_id,
            customer_id,
            reason,
            milestone_n,
            sale_id,
        )

    def prize(self, business_id: UUID) -> UUID:
        return self.one(
            "INSERT INTO prize_catalog (business_id, name, short_label, type, value, weight) "
            "VALUES (%s, 'Topping', 'Topping', 'extra_item', 0, 1) RETURNING id",
            business_id,
        )

    def redeemed_award(
        self,
        business_id: UUID,
        customer_id: UUID,
        spin_id: UUID,
        prize_id: UUID,
        sale_id: UUID,
        operator_id: UUID,
    ) -> UUID:
        return self.one(
            "INSERT INTO prize_award (business_id, customer_id, spin_id, prize_id, status, "
            "expires_at, redeemed_at, redeemed_sale_id, redeemed_by) "
            "VALUES (%s, %s, %s, %s, 'redeemed', now() + interval '90 days', now(), %s, %s) "
            "RETURNING id",
            business_id,
            customer_id,
            spin_id,
            prize_id,
            sale_id,
            operator_id,
        )


@dataclass
class Base:
    business_id: UUID
    operator_id: UUID
    workday_id: UUID
    customer_id: UUID


@pytest.fixture
def rows(owner_conn) -> Rows:
    return Rows(owner_conn)


@pytest.fixture
def base(rows: Rows, owner_conn) -> Base:
    business_id = rows.business()
    operator_id = rows.operator(business_id)
    workday_id = rows.workday(business_id, operator_id)
    customer_id = rows.customer(business_id)
    owner_conn.commit()
    return Base(business_id, operator_id, workday_id, customer_id)
