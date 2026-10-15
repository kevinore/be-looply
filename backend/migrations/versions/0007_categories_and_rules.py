"""product categories, and which products earn stamps or take prizes

Generic for any business:
- product_category: sections of the sale screen (e.g. "Bebidas", "Helados").
- product.earns_stamp: a sale earns a stamp (R8) only if it has at least one
  product that earns stamps. Copied to sale.earns_stamp when the sale is created.
- product.prize_eligible: prizes apply only to these products (R17).

Owner decision (2026-10-14): ice creams neither earn stamps nor take prizes.

Revision ID: 0007_categories_and_rules
Revises: 0006_payment_transfer
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_categories_and_rules"
down_revision: str | None = "0006_payment_transfer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(r"""
CREATE TABLE product_category (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id  uuid NOT NULL REFERENCES business(id),
  name         text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 40),
  sort_order   integer NOT NULL DEFAULT 0,
  active       boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, name)
);

ALTER TABLE product ADD COLUMN category_id uuid REFERENCES product_category(id);
ALTER TABLE product ADD COLUMN earns_stamp boolean NOT NULL DEFAULT true;
ALTER TABLE product ADD COLUMN prize_eligible boolean NOT NULL DEFAULT true;

-- Copy at sale time, so changing a product later never changes past cards.
ALTER TABLE sale ADD COLUMN earns_stamp boolean NOT NULL DEFAULT true;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
    EXECUTE 'GRANT SELECT, INSERT, UPDATE ON product_category TO app_runtime';
  END IF;
END $$;
""")


def downgrade() -> None:
    op.execute(r"""
ALTER TABLE sale DROP COLUMN earns_stamp;
ALTER TABLE product DROP COLUMN prize_eligible;
ALTER TABLE product DROP COLUMN earns_stamp;
ALTER TABLE product DROP COLUMN category_id;
DROP TABLE product_category;
""")
