"""Stamp rule (R8): which claimed sales earn a stamp on the customer's card.

The single place that decides it. The card (`purchases`, `progress`), milestone
spins (R9, R10), the `counted` flag of a claim and the operator screens all read
from here, so changing the rule means changing STAMP_RULE and nothing else.

Owner decision, 2026-10-13: every claimed sale earns exactly one stamp, whatever
the number of items and however soon after the previous purchase. This is
expected to change in the future; the previous rule (one stamp per workday) is
kept below, tested, and can be restored by switching STAMP_RULE.

Whatever the rule, only sales with sale.earns_stamp count: a sale earns stamps
when it has at least one product with product.earns_stamp (owner decision,
2026-10-14: ice creams alone don't earn stamps).
"""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import distinct, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Sale


class StampRule(StrEnum):
    # One stamp per claimed sale, no matter how many items or how close in time.
    PER_SALE = "per_sale"
    # One stamp per workday: a second sale the same day is linked but adds nothing.
    PER_WORKDAY = "per_workday"


STAMP_RULE = StampRule.PER_SALE


def _stamp_unit(rule: StampRule):
    """What a stamp is counted over: distinct sales or distinct workdays."""
    return Sale.workday_id if rule == StampRule.PER_WORKDAY else Sale.id


async def count_stamps(db: AsyncSession, customer_id: UUID) -> int:
    """Stamps on the card: claimed sales only (void and unlinked sales never count)."""
    return (
        await db.execute(
            select(func.count(distinct(_stamp_unit(STAMP_RULE)))).where(
                Sale.customer_id == customer_id,
                Sale.status == "claimed",
                Sale.earns_stamp.is_(True),
            )
        )
    ).scalar_one()


async def earns_stamp(db: AsyncSession, sale: Sale, customer_id: UUID) -> bool:
    """Whether linking `sale` adds a stamp. Call it before the sale is marked claimed."""
    if not sale.earns_stamp:
        return False
    if STAMP_RULE == StampRule.PER_SALE:
        return True
    already_today = (
        await db.execute(
            select(
                exists().where(
                    Sale.customer_id == customer_id,
                    Sale.workday_id == sale.workday_id,
                    Sale.status == "claimed",
                    Sale.earns_stamp.is_(True),
                )
            )
        )
    ).scalar()
    return not already_today
