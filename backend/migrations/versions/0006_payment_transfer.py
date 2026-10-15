"""payment method 'transfer'

Owner decision (2026-10-14): only three payment methods, cash, transfer and card.
'nequi' and 'breb' stay valid for sales recorded before; the API no longer
accepts them for new sales.

Revision ID: 0006_payment_transfer
Revises: 0005_product_options
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_payment_transfer"
down_revision: str | None = "0005_product_options"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(r"""
ALTER TABLE sale DROP CONSTRAINT sale_payment_method_check;
ALTER TABLE sale ADD CONSTRAINT sale_payment_method_check
  CHECK (payment_method IN ('cash','transfer','card','nequi','breb'));
""")


def downgrade() -> None:
    # Fails if any sale was paid by 'transfer' (data is never rewritten).
    op.execute(r"""
ALTER TABLE sale DROP CONSTRAINT sale_payment_method_check;
ALTER TABLE sale ADD CONSTRAINT sale_payment_method_check
  CHECK (payment_method IN ('cash','nequi','breb','card'));
""")
