from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import for_update
from app.core.errors import AppError, constraint_name
from app.core.time import now_utc
from app.models import Business, Customer, Sale, Spin
from app.services import customers
from app.services.events import emit_event

ClaimMethod = Literal["qr", "manual"]


@dataclass
class ClaimResult:
    counted: bool
    new_spins: list[Spin]
    card: dict


def validate_claimable(sale: Sale, method: ClaimMethod) -> None:
    """11.7 step 1 (the business check is done by the caller or link_sale_to_customer)."""
    if sale.status == "void":
        raise AppError("claim_voided")
    if sale.status == "claimed":
        raise AppError("claim_already_claimed")
    # R7: QR tokens expire at the end of the local day or when the workday closes.
    if method == "qr" and sale.claim_expires_at <= now_utc():
        raise AppError("claim_expired")


async def link_sale_to_customer(
    db: AsyncSession,
    sale: Sale,
    customer: Customer,
    method: ClaimMethod,
    actor: Literal["customer", "operator"],
    actor_id: UUID | None,
) -> ClaimResult:
    """The only way to link a sale to a customer (R6). The caller holds the sale lock."""
    validate_claimable(sale, method)
    if sale.business_id != customer.business_id:  # R21
        raise AppError("claim_not_found")

    await db.execute(for_update(select(Customer).where(Customer.id == customer.id)))

    # R8: only the first claimed sale of a workday counts as a purchase.
    counted = not (
        await db.execute(
            select(
                exists().where(
                    Sale.customer_id == customer.id,
                    Sale.workday_id == sale.workday_id,
                    Sale.status == "claimed",
                )
            )
        )
    ).scalar()

    sale.customer_id = customer.id
    sale.status = "claimed"
    sale.claimed_at = now_utc()
    sale.claim_method = method
    await db.flush()
    await emit_event(
        db,
        business_id=sale.business_id,
        type="sale_claimed",
        actor=actor,
        actor_id=actor_id,
        customer_id=customer.id,
        sale_id=sale.id,
        workday_id=sale.workday_id,
        payload={"method": method, "counted": counted},
    )
    new_spins = await reconcile_spins(db, customer, trigger_sale=sale)
    return ClaimResult(counted, new_spins, await build_card(db, customer))


async def reconcile_spins(
    db: AsyncSession, customer: Customer, trigger_sale: Sale | None = None
) -> list[Spin]:
    """Make active spins match purchases (R9, R10). Never touches consumed spins.

    Called after linking, unlinking and voiding. The caller holds the customer lock.
    """
    business = await db.get(Business, customer.business_id)
    purchases = await customers.purchases(db, customer.id)
    every = business.milestone_every

    expected: set[tuple[str, int | None]] = set()
    if purchases >= 1:
        expected.add(("welcome", None))  # R9
    expected |= {("milestone", n) for n in range(every, purchases + 1, every)}  # R10

    current = list(
        (
            await db.execute(
                for_update(
                    select(Spin).where(
                        Spin.customer_id == customer.id, Spin.status != "void"
                    )
                )
            )
        ).scalars()
    )
    have = {(s.reason, s.milestone_n) for s in current}

    created: list[Spin] = []
    missing = sorted(expected - have, key=lambda k: (k[0] != "welcome", k[1] or 0))
    if missing:
        unlocked_by = (
            trigger_sale.id
            if trigger_sale
            else await _latest_claimed_sale(db, customer.id)
        )
        for reason, milestone_n in missing:
            spin = Spin(
                business_id=customer.business_id,
                customer_id=customer.id,
                reason=reason,
                milestone_n=milestone_n,
                unlocked_by_sale_id=unlocked_by,
                status="available",
            )
            try:
                async with db.begin_nested():
                    db.add(spin)
                    await db.flush()
            except IntegrityError as exc:
                # 14.3: already exists -> ignore.
                if constraint_name(exc) in ("spin_one_welcome", "spin_one_milestone"):
                    continue
                raise
            created.append(spin)
            await emit_event(
                db,
                business_id=customer.business_id,
                type="spin_unlocked",
                actor="system",
                customer_id=customer.id,
                sale_id=unlocked_by,
                payload={
                    "spin_id": str(spin.id),
                    "reason": reason,
                    "milestone_n": milestone_n,
                },
            )

    now = now_utc()
    for spin in current:
        if spin.status != "available":
            continue
        unjustified = (spin.reason == "welcome" and purchases == 0) or (
            spin.reason == "milestone" and spin.milestone_n > purchases
        )
        if unjustified:
            spin.status = "void"
            spin.voided_at = now
            await db.flush()
            await emit_event(
                db,
                business_id=customer.business_id,
                type="spin_voided",
                actor="system",
                customer_id=customer.id,
                sale_id=spin.unlocked_by_sale_id,
                payload={"spin_id": str(spin.id), "reason": "reconcile"},
            )
    return created


async def _latest_claimed_sale(db: AsyncSession, customer_id: UUID) -> UUID:
    return (
        await db.execute(
            select(Sale.id)
            .where(Sale.customer_id == customer_id, Sale.status == "claimed")
            .order_by(Sale.claimed_at.desc())
            .limit(1)
        )
    ).scalar_one()


async def build_card(db: AsyncSession, customer: Customer) -> dict:
    business = await db.get(Business, customer.business_id)
    every = business.milestone_every
    purchases = await customers.purchases(db, customer.id)
    progress = purchases % every
    if purchases > 0 and progress == 0:
        progress = every
    spins = (
        await db.execute(
            select(Spin)
            .where(Spin.customer_id == customer.id, Spin.status == "available")
            .order_by(Spin.created_at)
        )
    ).scalars()
    return {
        "customer": {
            "id": customer.id,
            "alias": customer.alias,
            "phone_last4": customers.phone_last4(customer.phone),
        },
        "purchases": purchases,
        "milestone_every": every,
        "progress": progress,
        "purchases_to_next_spin": every - (purchases % every),
        "available_spins": [
            {"id": s.id, "reason": s.reason, "milestone_n": s.milestone_n}
            for s in spins
        ],
        "active_prizes": [
            {
                "id": award.id,
                "name": prize.name,
                "short_label": prize.short_label,
                "type": prize.type,
                "awarded_at": award.awarded_at,
                "expires_at": award.expires_at,
            }
            for award, prize in await customers.active_prizes(db, customer.id)
        ],
    }
