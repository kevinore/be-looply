from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import for_update
from app.core.errors import AppError
from app.core.time import now_utc
from app.models import Customer, Operator, PrizeAward, Sale, Spin, Workday
from app.services.claims import reconcile_spins
from app.services.events import emit_event


async def cascade_spins(db: AsyncSession, sale: Sale, operator: Operator) -> None:
    """11.8 step 3: spins unlocked by this sale. Lock order: spin -> prize_award."""
    spins = (
        await db.execute(
            for_update(
                select(Spin)
                .where(Spin.unlocked_by_sale_id == sale.id, Spin.status != "void")
                .order_by(Spin.created_at)
            )
        )
    ).scalars()
    now = now_utc()
    for spin in list(spins):
        common = {
            "business_id": sale.business_id,
            "customer_id": spin.customer_id,
            "sale_id": sale.id,
        }
        if spin.status == "available":
            _void_spin(spin, now)
            await db.flush()
            await emit_event(
                db,
                type="spin_voided",
                actor="system",
                payload={"spin_id": str(spin.id)},
                **common,
            )
            continue
        # consumed
        award = (
            await db.execute(
                for_update(select(PrizeAward).where(PrizeAward.spin_id == spin.id))
            )
        ).scalar_one_or_none()
        # Decision beyond the plan (confirmed by the owner): a prize won from this
        # sale AND redeemed on this same sale is voided too, not restored in step 4.
        used_here = award is not None and award.redeemed_sale_id == sale.id
        if award is not None and (award.status == "active" or used_here):
            previous_status = award.status
            award.status = "void"
            award.voided_at = now
            # CHECK: only 'redeemed' may have all redemption fields set.
            award.redeemed_at = None
            award.redeemed_sale_id = None
            award.redeemed_by = None
            _void_spin(spin, now)
            await db.flush()
            await emit_event(
                db,
                type="prize_voided",
                actor="system",
                payload={
                    "prize_award_id": str(award.id),
                    "previous_status": previous_status,
                    "redeemed_sale_id": str(sale.id) if used_here else None,
                },
                **common,
            )
            await emit_event(
                db,
                type="spin_voided",
                actor="system",
                payload={"spin_id": str(spin.id)},
                **common,
            )
        elif award is not None and award.status == "redeemed":
            # Already used on another sale: never touched. Audit only.
            await emit_event(
                db,
                type="void_left_redeemed_prize",
                actor="operator",
                actor_id=operator.id,
                payload={"prize_award_id": str(award.id), "spin_id": str(spin.id)},
                **common,
            )


async def restore_prize_used(db: AsyncSession, sale: Sale, operator: Operator) -> None:
    """11.8 step 4: a prize redeemed on this sale goes back to active."""
    awards = (
        await db.execute(
            for_update(
                select(PrizeAward).where(
                    PrizeAward.redeemed_sale_id == sale.id,
                    PrizeAward.status == "redeemed",
                )
            )
        )
    ).scalars()
    for award in list(awards):
        award.status = "active"
        award.redeemed_at = None
        award.redeemed_sale_id = None
        award.redeemed_by = None
        await db.flush()
        await emit_event(
            db,
            business_id=sale.business_id,
            type="prize_restored",
            actor="operator",
            actor_id=operator.id,
            customer_id=award.customer_id,
            sale_id=sale.id,
            payload={"prize_award_id": str(award.id)},
        )


def _void_spin(spin: Spin, now) -> None:
    spin.status = "void"
    spin.voided_at = now


async def void_sale(db: AsyncSession, sale_id, reason: str, operator: Operator) -> Sale:
    """R19: nothing is deleted. Voiding marks `void` and cascades (11.8)."""
    sale = (
        await db.execute(
            for_update(
                select(Sale).where(
                    Sale.id == sale_id, Sale.business_id == operator.business_id
                )
            )
        )
    ).scalar_one_or_none()
    if sale is None:
        raise AppError("sale_not_found")
    if sale.status == "void":
        raise AppError("sale_already_void")
    if operator.role != "owner":
        workday = await db.get(Workday, sale.workday_id)
        if workday.status != "open":
            raise AppError("forbidden")

    customer = None
    if sale.customer_id is not None:
        customer = (
            await db.execute(
                for_update(select(Customer).where(Customer.id == sale.customer_id))
            )
        ).scalar_one()

    await cascade_spins(db, sale, operator)
    await restore_prize_used(db, sale, operator)

    previous_status = sale.status
    sale.status = "void"
    sale.voided_at = now_utc()
    sale.voided_by = operator.id
    sale.void_reason = reason
    # If it was claimed, customer_id is kept as history.
    await db.flush()

    if customer is not None:
        await reconcile_spins(db, customer)
    await emit_event(
        db,
        business_id=sale.business_id,
        type="sale_voided",
        actor="operator",
        actor_id=operator.id,
        customer_id=sale.customer_id,
        sale_id=sale.id,
        workday_id=sale.workday_id,
        payload={"reason": reason, "previous_status": previous_status},
    )
    return sale
