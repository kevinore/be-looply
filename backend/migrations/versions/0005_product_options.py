"""product options: groups of choices a product needs at sale time

Generic for any business: a product can be linked to option groups (e.g. "Base",
"Té"), each with a min/max number of choices. The chosen options are copied to
the sale line, like the label and the price.

Revision ID: 0005_product_options
Revises: 0004_drop_purchases_view
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_product_options"
down_revision: str | None = "0004_drop_purchases_view"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(r"""
-- Fixed information shown with the product (e.g. the fruit of a drink).
ALTER TABLE product ADD COLUMN description text;

CREATE TABLE option_group (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id  uuid NOT NULL REFERENCES business(id),
  name         text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 40),
  min_select   smallint NOT NULL DEFAULT 1 CHECK (min_select >= 0),
  max_select   smallint NOT NULL DEFAULT 1 CHECK (max_select >= 1),
  sort_order   integer NOT NULL DEFAULT 0,
  active       boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, name),
  CHECK (min_select <= max_select)
);

CREATE TABLE option_choice (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id         uuid NOT NULL REFERENCES option_group(id),
  name             text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 40),
  price_delta_cop  integer NOT NULL DEFAULT 0 CHECK (price_delta_cop >= 0),
  sort_order       integer NOT NULL DEFAULT 0,
  active           boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (group_id, name)
);

-- Nothing is deleted (R19): an unlinked group keeps its row with active = false.
CREATE TABLE product_option_group (
  product_id  uuid NOT NULL REFERENCES product(id),
  group_id    uuid NOT NULL REFERENCES option_group(id),
  sort_order  integer NOT NULL DEFAULT 0,
  active      boolean NOT NULL DEFAULT true,
  PRIMARY KEY (product_id, group_id)
);

-- Copy of each chosen option at sale time.
CREATE TABLE sale_item_option (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sale_item_id     uuid NOT NULL REFERENCES sale_item(id),
  option_id        uuid NOT NULL REFERENCES option_choice(id),
  group_name       text NOT NULL,
  option_name      text NOT NULL,
  price_delta_cop  integer NOT NULL DEFAULT 0 CHECK (price_delta_cop >= 0),
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sale_item_option_item ON sale_item_option (sale_item_id);

-- Default privileges (0003) already cover these tables; explicit in case the
-- migration role differs. R19: still no DELETE.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
    EXECUTE 'GRANT SELECT, INSERT, UPDATE ON option_group, option_choice, '
            'product_option_group, sale_item_option TO app_runtime';
  END IF;
END $$;
""")


def downgrade() -> None:
    op.execute(r"""
DROP TABLE sale_item_option;
DROP TABLE product_option_group;
DROP TABLE option_choice;
DROP TABLE option_group;
ALTER TABLE product DROP COLUMN description;
""")
