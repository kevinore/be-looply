from datetime import timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import for_update
from app.core.errors import AppError
from app.core.time import now_utc
from app.models import (
    Operator,
    PrizeAward,
    PrizeCatalog,
    Product,
    ProductCategory,
    Sale,
    SaleItem,
)
from app.schemas.prize import WheelPrizeIn
from app.services import options
from app.services.events import emit_event, jsonable


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
    """R17: over one unit of a product, capped by max_value_cop."""
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
    # The same product can be in several lines (different options): the prize
    # goes to the most expensive one.
    matches = [line for line in lines if line["product_id"] == target_product_id]
    target = max(matches, key=lambda line: line["unit_price_cop"], default=None)
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


def applies_to(prize: PrizeCatalog, product: Product) -> bool:
    """R17: the product takes prizes and is in the prize's category (if it has one)."""
    return product.prize_eligible and (
        prize.category_id is None or product.category_id == prize.category_id
    )


async def sale_has_product_for(
    db: AsyncSession, sale_id: UUID, prize: PrizeCatalog
) -> bool:
    """Whether the sale has a product the prize applies to (see applies_to)."""
    conditions = [
        SaleItem.sale_id == sale_id,
        SaleItem.product_id == Product.id,
        Product.prize_eligible.is_(True),
    ]
    if prize.category_id is not None:
        conditions.append(Product.category_id == prize.category_id)
    return (await db.execute(select(exists().where(*conditions)))).scalar()


async def redeem_on_paid_sale(
    db: AsyncSession,
    sale: Sale,
    prize_award_id: UUID,
    product_id: UUID | None,
    operator: Operator,
    option_ids: list[UUID] | None = None,
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
        if not applies_to(prize, product):  # R17
            raise AppError("prize_target_invalid")
        groups = await options.product_groups(db, [product.id])
        chosen = options.resolve_choices(groups.get(product.id, []), option_ids or [])
        price = product.price_cop + sum(c.price_delta_cop for _, c in chosen)
        discount = unit_discount(prize, price)
        # The difference is never charged in this flow: do it as a new sale.
        if discount < price:
            raise AppError("prize_target_invalid")
        item = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            label=product.name,
            qty=1,
            unit_price_cop=price,
            unit_cost_cop=product.cost_cop,
            discount_cop=discount,
            prize_award_id=award.id,
        )
    else:  # extra_item
        # R17: it goes with a product that takes this prize, so the sale needs one.
        if not await sale_has_product_for(db, sale.id, prize):
            raise AppError("prize_target_invalid")
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
    if prize.type == "free_item":
        options.add_item_options(db, item, options.option_rows(chosen))
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


async def catalog(db: AsyncSession, business_id: UUID) -> list[dict]:
    """Every prize of the business (owner only: includes weights), in wheel order."""
    prizes = (
        await db.execute(
            select(PrizeCatalog)
            .where(PrizeCatalog.business_id == business_id)
            .order_by(PrizeCatalog.sort_order, PrizeCatalog.name)
        )
    ).scalars()
    awarded = await awarded_prize_ids(db, business_id)
    return [{**_snapshot(p), "awarded": p.id in awarded} for p in prizes]


async def awarded_prize_ids(db: AsyncSession, business_id: UUID) -> set[UUID]:
    """Prizes won at least once (any status): their reward can no longer change."""
    return set(
        (
            await db.execute(
                select(PrizeAward.prize_id)
                .where(PrizeAward.business_id == business_id)
                .distinct()
            )
        ).scalars()
    )


# Wheel editor. Weights are hundredths of a percent: the active prizes add up to
# exactly 100% (10 000). The draw only needs relative weights, so older catalogs
# with other totals keep working until they are saved from the editor.
WHEEL_TOTAL = 10_000
MIN_ACTIVE_PRIZES = 2
MAX_ACTIVE_PRIZES = 12
# What a customer holds once won: never changed afterwards (retire + create instead).
REWARD_FIELDS = ("type", "value", "max_value_cop", "category_id")


def _snapshot(p: PrizeCatalog) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "short_label": p.short_label,
        "type": p.type,
        "value": p.value,
        "max_value_cop": p.max_value_cop,
        "category_id": p.category_id,
        "weight": p.weight,
        "expires_days": p.expires_days,
        "color": p.color,
        "sort_order": p.sort_order,
        "active": p.active,
    }


def _wheel_values(item: WheelPrizeIn, sort_order: int) -> dict:
    """Editor row -> prize_catalog columns, with the reward normalized by type."""
    if item.type == "percent_off" and not 1 <= item.value <= 100:
        raise AppError("validation_error")
    return {
        "name": item.name,
        "short_label": item.short_label,
        "type": item.type,
        # Only percent_off uses `value`; extra_item is never capped (R17).
        "value": item.value if item.type == "percent_off" else 0,
        "max_value_cop": None if item.type == "extra_item" else item.max_value_cop,
        "category_id": item.category_id,
        "weight": item.weight,
        "expires_days": item.expires_days,
        "color": item.color,
        "sort_order": sort_order,
        "active": item.active,
    }


async def save_wheel(
    db: AsyncSession, business_id: UUID, operator: Operator, items: list[WheelPrizeIn]
) -> None:
    """Replace the wheel in one transaction (owner only). Nothing is deleted (R19).

    `items` lists every prize of the business in display order; prizes without an
    id are created. A prize already won keeps its reward (REWARD_FIELDS).
    """
    current = {
        p.id: p
        for p in (
            await db.execute(
                for_update(
                    select(PrizeCatalog).where(PrizeCatalog.business_id == business_id)
                )
            )
        ).scalars()
    }
    ids = [i.id for i in items if i.id is not None]
    # Every existing prize, once: leaving one out must not silently retire it.
    if len(ids) != len(set(ids)) or set(ids) != set(current):
        raise AppError("validation_error")
    names = [i.name.casefold() for i in items]
    if len(names) != len(set(names)):
        raise AppError("prize_name_taken")
    rows = [_wheel_values(item, order) for order, item in enumerate(items, start=1)]
    active = [r for r in rows if r["active"]]
    if not MIN_ACTIVE_PRIZES <= len(active) <= MAX_ACTIVE_PRIZES:
        raise AppError("wheel_size_invalid")
    if sum(r["weight"] for r in active) != WHEEL_TOTAL:
        raise AppError("wheel_total_invalid")
    # R21: a prize can only point to a category of its own business.
    wanted = {r["category_id"] for r in rows} - {None}
    if wanted:
        found = set(
            (
                await db.execute(
                    select(ProductCategory.id).where(
                        ProductCategory.id.in_(wanted),
                        ProductCategory.business_id == business_id,
                    )
                )
            ).scalars()
        )
        if found != wanted:
            raise AppError("validation_error")

    awarded = await awarded_prize_ids(db, business_id)
    before = [jsonable(_snapshot(p)) for p in current.values()]
    for item, values in zip(items, rows, strict=True):
        if item.id is None:
            db.add(PrizeCatalog(business_id=business_id, **values))
            continue
        prize = current[item.id]
        if prize.id in awarded and any(
            getattr(prize, f) != values[f] for f in REWARD_FIELDS
        ):
            raise AppError("prize_locked", extra={"prize_id": str(prize.id)})
        for key, value in values.items():
            setattr(prize, key, value)
    await db.flush()

    after = await catalog(db, business_id)
    await emit_event(
        db,
        business_id=business_id,
        type="prize_catalog_updated",
        actor="operator",
        actor_id=operator.id,
        payload={"before": before, "after": [jsonable(p) for p in after]},
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
