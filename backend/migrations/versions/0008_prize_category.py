"""prize category: which section of products a prize applies to

Generic for any business: prize_catalog.category_id limits a prize to the
products of one category (e.g. "Helados" for a free ice cream, "Bebidas" for a
drink discount). NULL = any product that takes prizes (product.prize_eligible).

Owner decision (2026-10-16): the wheel has ice cream prizes, so ice creams take
prizes again, but only the prizes of their own category.

Revision ID: 0008_prize_category
Revises: 0007_categories_and_rules
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_prize_category"
down_revision: str | None = "0007_categories_and_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(r"""
ALTER TABLE prize_catalog ADD COLUMN category_id uuid REFERENCES product_category(id);
""")


def downgrade() -> None:
    op.execute(r"""
ALTER TABLE prize_catalog DROP COLUMN category_id;
""")
