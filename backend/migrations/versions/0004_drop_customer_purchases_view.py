"""drop v_customer_purchases (stamp rule moved to app/services/stamps.py)

The view hard-coded R8 as "one stamp per workday". The rule now lives in one
Python module so it can change without a migration.

Revision ID: 0004_drop_purchases_view
Revises: 0003_grants
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_drop_purchases_view"
down_revision: str | None = "0003_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP VIEW v_customer_purchases;")


def downgrade() -> None:
    op.execute(r"""
CREATE VIEW v_customer_purchases AS
SELECT c.id AS customer_id,
       c.business_id,
       COUNT(DISTINCT s.workday_id) FILTER (WHERE s.status = 'claimed') AS purchases
FROM customer c
LEFT JOIN sale s ON s.customer_id = c.id
GROUP BY c.id, c.business_id;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
    EXECUTE 'GRANT SELECT ON v_customer_purchases TO app_runtime';
  END IF;
END $$;
""")
