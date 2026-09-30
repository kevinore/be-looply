from datetime import timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import for_update
from app.core.errors import AppError
from app.core.time import now_utc
from app.models import Operator, PrizeAward, PrizeCatalog, Product, Sale, SaleItem
from app.services.events import emit_event


async def lock_valid_prize(
    db: AsyncSession, business_id: UUID, customer_id: UUID, prize_award_id: UUID
) -> tuple[PrizeAward, PrizeCatalog]:
    """11.9.1 step 1. Same error for another customer's prize: do not reveal it."""
    award = (
        await db.execute(
            for_update(
                select(PrizeAward).where(
                    PrizeAward.id == prize_award_id,
                    PrizeAward.business_id == business_id,
                    PrizeAward.customer_id == customer_id,
                )
            )
        )
    ).scalar_one_or_none()
    if award is None:
        raise AppError("prize_not_found")
    if award.status != "active":
        raise AppError("prize_not_active")
    if award.expires_at <= now_utc():
        raise AppError("prize_expired")
    return award, await db.get(PrizeCatalog, award.prize_id)


def unit_discount(prize: PrizeCatalog, price: int) -> int:
    """R17: over one unit of a drink, capped by max_value_cop."""
    cap = prize.max_value_cop or price
    if prize.type == "percent_off":
        return min(round(price * prize.value / 100), cap)
    if prize.type == "free_item":
        return min(price, cap)
    return 0


def apply_at_creation(
    prize: PrizeCatalog, award: PrizeAward, lines: list[dict], target_product_id: UUID
) -> None:
    """11.9.1 steps 2-3: mutate the sale lines before insert."""
    target = next(
        (line for line in lines if line["product_id"] == target_product_id), None
    )
    if target is None:
        raise AppError("prize_target_invalid")
    if prize.type == "extra_item":
        lines.append(
            {
                "product_id": None,
                "label": prize.name,
                "qty": 1,
                "unit_price_cop": 0,
                "unit_cost_cop": None,
                "discount_cop": 0,
                "prize_award_id": award.id,
            }
        )
        return
    target["discount_cop"] += unit_discount(prize, target["unit_price_cop"])
    target["prize_award_id"] = award.id


async def mark_redeemed(
    db: AsyncSession,
    award: PrizeAward,
    prize: PrizeCatalog,
    sale: Sale,
    operator: Operator,
) -> None:
    """R15: only the operator redeems. R16: prize_one_per_sale -> prize_already_in_sale."""
    award.status = "redeemed"
    award.redeemed_at = now_utc()
    award.redeemed_sale_id = sale.id
    award.redeemed_by = operator.id
    await db.flush()
    await emit_event(
        db,
        business_id=sale.business_id,
        type="prize_redeemed",
        actor="operator",
        actor_id=operator.id,
        customer_id=award.customer_id,
        sale_id=sale.id,
        workday_id=sale.workday_id,
        payload={"prize_award_id": str(award.id), "prize_type": prize.type},
    )


async def sale_has_redeemed_prize(db: AsyncSession, sale_id: UUID) -> bool:
    return (
        await db.execute(
            select(
                exists().where(
                    PrizeAward.redeemed_sale_id == sale_id,
                    PrizeAward.status == "redeemed",
                )
            )
        )
    ).scalar()


async def redeem_on_paid_sale(
    db: AsyncSession,
    sale: Sale,
    prize_award_id: UUID,
    product_id: UUID | None,
    operator: Operator,
) -> None:
    """11.9.2 steps 2-8. The caller holds the sale lock (claimed, open workday)."""
    award, prize = await lock_valid_prize(
        db, sale.business_id, sale.customer_id, prize_award_id
    )
    if prize.type == "percent_off":  # R18
        raise AppError("discount_needs_new_sale")
    if await sale_has_redeemed_prize(db, sale.id):  # R16
        raise AppError("prize_already_in_sale")

    if prize.type == "free_item":
        if product_id is None:
            raise AppError("validation_error")
        product = (
            await db.execute(
                select(Product).where(
                    Product.id == product_id,
                    Product.business_id == sale.business_id,
                    Product.active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if product is None:
            raise AppError("product_invalid")
        discount = unit_discount(prize, product.price_cop)
        # The difference is never charged in this flow: do it as a new sale.
        if discount < product.price_cop:
            raise AppError("prize_target_invalid")
        item = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            label=product.name,
            qty=1,
            unit_price_cop=product.price_cop,
            unit_cost_cop=product.cost_cop,
            discount_cop=discount,
            prize_award_id=award.id,
        )
    else:  # extra_item
        item = SaleItem(
            sale_id=sale.id,
            product_id=None,
            label=prize.name,
            qty=1,
            unit_price_cop=0,
            unit_cost_cop=None,
            discount_cop=0,
            prize_award_id=award.id,
        )
    db.add(item)
    await db.flush()
    # total_cop does not change: net $0 line.
    await mark_redeemed(db, award, prize, sale, operator)


async def award_prize(
    db: AsyncSession,
    spin_id: UUID,
    customer_id: UUID,
    business_id: UUID,
    prize: PrizeCatalog,
) -> PrizeAward:
    """R13: expires expires_days after being won."""
    award = PrizeAward(
        business_id=business_id,
        customer_id=customer_id,
        spin_id=spin_id,
        prize_id=prize.id,
        status="active",
        awarded_at=now_utc(),
        expires_at=now_utc() + timedelta(days=prize.expires_days),
    )
    db.add(award)
    await db.flush()
    return award


PendingFilter = Literal["expiring", "free", "all"]


async def pending_prizes(
    db: AsyncSession, business_id: UUID, filter: PendingFilter
) -> list[dict]:
    """11.9.3, from v_pending_prizes, ordered by expires_at."""
    sql = "SELECT * FROM v_pending_prizes WHERE business_id = :business_id"
    params: dict = {"business_id": business_id}
    if filter == "expiring":
        sql += " AND expires_at <= :limit"
        params["limit"] = now_utc() + timedelta(days=7)
    elif filter == "free":
        sql += " AND prize_type = 'free_item'"
    sql += " ORDER BY expires_at"
    return [dict(r) for r in (await db.execute(text(sql), params)).mappings()]


async def catalog(db: AsyncSession, business_id: UUID) -> list[PrizeCatalog]:
    return list(
        (
            await db.execute(
                select(PrizeCatalog)
                .where(PrizeCatalog.business_id == business_id)
                .order_by(PrizeCatalog.sort_order, PrizeCatalog.name)
            )
        ).scalars()
    )


async def active_catalog(db: AsyncSession, business_id: UUID) -> list[PrizeCatalog]:
    """Wheel segments, in sort_order. Weights never leave the API (R12)."""
    return list(
        (
            await db.execute(
                select(PrizeCatalog)
                .where(
                    PrizeCatalog.business_id == business_id,
                    PrizeCatalog.active.is_(True),
                )
                .order_by(PrizeCatalog.sort_order, PrizeCatalog.name)
            )
        ).scalars()
    )
