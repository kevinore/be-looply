import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import for_update
from app.core.errors import AppError
from app.core.time import end_of_local_day
from app.models import Customer, PrizeAward, PrizeCatalog, Product, Sale, SaleItem
from app.schemas.sale import SaleCreateIn
from app.services import customers, options, prizes
from app.services.auth_operator import OperatorContext
from app.services.claims import ClaimResult, link_sale_to_customer, reconcile_spins
from app.services.events import emit_event
from app.services.voids import cascade_spins, restore_prize_used
from app.services.workdays import require_open_workday


async def find_by_idempotency_key(
    db: AsyncSession, business_id: UUID, key: UUID
) -> Sale | None:
    sale = (
        await db.execute(select(Sale).where(Sale.idempotency_key == key))
    ).scalar_one_or_none()
    if sale is not None and sale.business_id != business_id:
        raise AppError("validation_error")
    return sale


async def create_sale(
    db: AsyncSession, ctx: OperatorContext, body: SaleCreateIn, idempotency_key: UUID
) -> tuple[Sale, bool]:
    """11.5. Returns (sale, created). R1: only an authenticated operator creates sales."""
    business, operator = ctx.business, ctx.operator

    # 1. Same key already used -> return that sale, create nothing.
    existing = await find_by_idempotency_key(db, business.id, idempotency_key)
    if existing is not None:
        return existing, False

    # 2.
    workday = await require_open_workday(db, business.id)

    # 3. R3: prices always come from the database.
    wanted = {item.product_id for item in body.items}
    products = {
        p.id: p
        for p in (
            await db.execute(
                select(Product).where(
                    Product.id.in_(wanted),
                    Product.business_id == business.id,
                    Product.active.is_(True),
                )
            )
        ).scalars()
    }
    if len(products) != len(wanted):
        raise AppError("product_invalid")
    groups = await options.product_groups(db, list(wanted))

    # 4. Price and cost are copied to sale_item; chosen options to sale_item_option.
    # The unit price includes the price of the options.
    lines = []
    for item in body.items:
        product = products[item.product_id]
        chosen = options.resolve_choices(
            groups.get(item.product_id, []), item.option_ids
        )
        lines.append(
            {
                "product_id": product.id,
                "label": product.name,
                "qty": item.qty,
                "unit_price_cop": product.price_cop
                + sum(c.price_delta_cop for _, c in chosen),
                "unit_cost_cop": product.cost_cop,
                "discount_cop": 0,
                "prize_award_id": None,
                "options": options.option_rows(chosen),
            }
        )

    # 5.
    customer = None
    if body.customer_id is not None:
        customer = (
            await db.execute(
                for_update(
                    select(Customer).where(
                        Customer.id == body.customer_id,
                        Customer.business_id == business.id,
                    )
                )
            )
        ).scalar_one_or_none()
        if customer is None:
            raise AppError("customer_not_found")

    # 6. Apply prize at creation (11.9.1).
    award: PrizeAward | None = None
    prize: PrizeCatalog | None = None
    if body.prize_award_id is not None:
        award, prize = await prizes.lock_valid_prize(
            db, business.id, customer.id, body.prize_award_id
        )
        # R17: only products that take this prize (its category).
        target = products.get(body.prize_target_product_id)
        if target is not None and not prizes.applies_to(prize, target):
            raise AppError("prize_target_invalid")
        prizes.apply_at_creation(prize, award, lines, body.prize_target_product_id)

    # 7.
    total = sum(
        line["unit_price_cop"] * line["qty"] - line["discount_cop"] for line in lines
    )

    # 8-9. R2: a sale is born paid. R6: single-use claim token.
    sale = Sale(
        business_id=business.id,
        workday_id=workday.id,
        operator_id=operator.id,
        status="paid",
        payment_method=body.payment_method,
        total_cop=total,
        idempotency_key=idempotency_key,
        claim_token=secrets.token_urlsafe(24),
        claim_expires_at=end_of_local_day(business.timezone),  # R7
        # R8: earns a stamp only with at least one product that earns stamps.
        earns_stamp=any(p.earns_stamp for p in products.values()),
    )
    db.add(sale)
    await db.flush()
    for line in lines:
        chosen = line.pop("options", [])
        item = SaleItem(sale_id=sale.id, **line)
        db.add(item)
        await db.flush()
        options.add_item_options(db, item, chosen)
    await db.flush()
    await db.refresh(sale)

    # 10.
    await emit_event(
        db,
        business_id=business.id,
        type="sale_paid",
        actor="operator",
        actor_id=operator.id,
        sale_id=sale.id,
        workday_id=workday.id,
        payload={
            "total_cop": total,
            "payment_method": body.payment_method,
            "items": [
                {
                    "product_id": str(i.product_id),
                    "qty": i.qty,
                    "option_ids": [str(o) for o in i.option_ids],
                }
                for i in body.items
            ],
        },
    )

    # 11.
    if customer is not None:
        await link_sale_to_customer(
            db, sale, customer, "manual", "operator", operator.id
        )

    # 12.
    if award is not None:
        await prizes.mark_redeemed(db, award, prize, sale, operator)
    return sale, True


async def get_sale(
    db: AsyncSession, business_id: UUID, sale_id: UUID, *, lock=False
) -> Sale:
    stmt = select(Sale).where(Sale.id == sale_id, Sale.business_id == business_id)
    sale = (await db.execute(for_update(stmt) if lock else stmt)).scalar_one_or_none()
    if sale is None:
        raise AppError("sale_not_found")
    return sale


def claim_url(sale: Sale) -> str:
    return f"{settings.PUBLIC_APP_URL.rstrip('/')}/client/claim/{sale.claim_token}"


async def sale_detail(db: AsyncSession, sale: Sale) -> dict:
    items = list(
        (
            await db.execute(
                select(SaleItem)
                .where(SaleItem.sale_id == sale.id)
                .order_by(SaleItem.created_at)
            )
        ).scalars()
    )
    customer = None
    if sale.customer_id is not None:
        c = await db.get(Customer, sale.customer_id)
        customer = {
            "id": c.id,
            "alias": c.alias,
            "phone_last4": customers.phone_last4(c.phone),
        }
    return {
        "id": sale.id,
        "workday_id": sale.workday_id,
        "status": sale.status,
        "total_cop": sale.total_cop,
        "payment_method": sale.payment_method,
        "items": await options.item_dicts(db, items),
        "claim_url": claim_url(sale),
        "claim_expires_at": sale.claim_expires_at,
        "claim_method": sale.claim_method,
        "paid_at": sale.paid_at,
        "claimed_at": sale.claimed_at,
        "voided_at": sale.voided_at,
        "void_reason": sale.void_reason,
        "customer": customer,
    }


async def sale_status(db: AsyncSession, sale: Sale) -> dict:
    """Polled every 2 s by the operator while the QR is shown (11.6)."""
    if sale.customer_id is None:
        return {"status": sale.status, "customer": None}
    c = await db.get(Customer, sale.customer_id)
    return {
        "status": sale.status,
        "customer": {
            "id": c.id,
            "alias": c.alias,
            "phone_last4": customers.phone_last4(c.phone),
            "purchases": await customers.purchases(db, c.id),
            "active_prizes": [
                {"id": a.id, "name": p.name, "type": p.type, "expires_at": a.expires_at}
                for a, p in await customers.active_prizes(db, c.id)
            ],
        },
    }


async def lock_modifiable_sale(
    db: AsyncSession, ctx: OperatorContext, sale_id: UUID, status: str
) -> Sale:
    """Sale of the business, with `status`, in the open workday; else sale_not_linkable."""
    workday = await require_open_workday(db, ctx.business.id)
    sale = (
        await db.execute(
            for_update(
                select(Sale).where(
                    Sale.id == sale_id, Sale.business_id == ctx.business.id
                )
            )
        )
    ).scalar_one_or_none()
    if sale is None or sale.status != status or sale.workday_id != workday.id:
        raise AppError("sale_not_linkable")
    return sale


async def link_manual(
    db: AsyncSession, ctx: OperatorContext, sale_id: UUID, customer_id: UUID
) -> ClaimResult:
    """F4: link without scanning (11.6)."""
    sale = await lock_modifiable_sale(db, ctx, sale_id, "paid")
    customer = await customers.get_customer(db, ctx.business.id, customer_id)
    result = await link_sale_to_customer(
        db, sale, customer, "manual", "operator", ctx.operator.id
    )
    await emit_event(
        db,
        business_id=sale.business_id,
        type="sale_linked_manual",
        actor="operator",
        actor_id=ctx.operator.id,
        customer_id=customer.id,
        sale_id=sale.id,
        workday_id=sale.workday_id,
    )
    return result


async def unlink(db: AsyncSession, ctx: OperatorContext, sale_id: UUID) -> Sale:
    """ "No es Ana" (11.6)."""
    sale = await lock_modifiable_sale(db, ctx, sale_id, "claimed")
    if await prizes.sale_has_redeemed_prize(db, sale.id):
        raise AppError("sale_has_prize")
    customer = (
        await db.execute(
            for_update(select(Customer).where(Customer.id == sale.customer_id))
        )
    ).scalar_one()

    # 11.8 steps 3-4, without touching the sale status yet.
    await cascade_spins(db, sale, ctx.operator)
    await restore_prize_used(db, sale, ctx.operator)

    sale.status = "paid"
    sale.customer_id = None
    sale.claimed_at = None
    sale.claim_method = None
    await db.flush()
    await reconcile_spins(db, customer)
    await emit_event(
        db,
        business_id=sale.business_id,
        type="sale_unlinked",
        actor="operator",
        actor_id=ctx.operator.id,
        customer_id=customer.id,
        sale_id=sale.id,
        workday_id=sale.workday_id,
    )
    return sale
