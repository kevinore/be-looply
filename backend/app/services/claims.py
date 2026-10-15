from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import for_update
from app.core.errors import AppError, constraint_name
from app.core.phone import normalize_phone
from app.core.time import now_utc
from app.models import Business, Customer, Sale, SaleItem, Spin
from app.services import customers, stamps
from app.services.events import emit_event

ClaimMethod = Literal["qr", "manual"]


@dataclass
class ClaimResult:
    counted: bool
    new_spins: list[Spin]
    card: dict
    # False when the sale has no product that earns stamps (e.g. only ice cream).
    stamp_eligible: bool = True


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

    # R8: whether this sale adds a stamp is decided in services/stamps.py.
    counted = await stamps.earns_stamp(db, sale, customer.id)

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
    return ClaimResult(
        counted, new_spins, await build_card(db, customer), sale.earns_stamp
    )


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


async def lock_sale_by_token(db: AsyncSession, claim_token: str) -> Sale:
    sale = (
        await db.execute(
            for_update(select(Sale).where(Sale.claim_token == claim_token))
        )
    ).scalar_one_or_none()
    if sale is None:
        raise AppError("claim_not_found")
    return sale


async def claim_preview(db: AsyncSession, claim_token: str) -> dict:
    """Entry screen preview, without personal data (11.10). Always a 200 response."""
    sale = (
        await db.execute(select(Sale).where(Sale.claim_token == claim_token))
    ).scalar_one_or_none()
    if sale is None:
        return {"state": "not_found", "sale": None, "business": None}
    if sale.status == "void":
        state = "voided"
    elif sale.status == "claimed":
        state = "already_claimed"
    elif sale.claim_expires_at <= now_utc():
        state = "expired"
    else:
        state = "claimable"
    items_count = (
        await db.execute(
            select(func.coalesce(func.sum(SaleItem.qty), 0)).where(
                SaleItem.sale_id == sale.id, SaleItem.product_id.is_not(None)
            )
        )
    ).scalar_one()
    business = await db.get(Business, sale.business_id)
    return {
        "state": state,
        "sale": {
            "items_count": items_count,
            "total_cop": sale.total_cop,
            "paid_at": sale.paid_at,
        },
        "business": {"name": business.name, "branding": business.branding},
    }


async def register(
    db: AsyncSession,
    *,
    phone: str,
    alias: str,
    consent: bool,
    claim_token: str,
    user_agent: str | None,
) -> tuple[ClaimResult, str]:
    """R5: registering requires a valid, unclaimed claim_token. Returns (result, token)."""
    if consent is not True:
        raise AppError("consent_required")
    alias = alias.strip()
    if not 2 <= len(alias) <= 30:
        raise AppError("validation_error")
    phone = normalize_phone(phone)

    # Validate the sale before creating anything.
    sale = await lock_sale_by_token(db, claim_token)
    validate_claimable(sale, "qr")

    existing = (
        await db.execute(
            select(Customer).where(
                Customer.business_id == sale.business_id, Customer.phone == phone
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Only here the alias is revealed, and only because the token is valid (R5).
        raise AppError(
            "customer_exists",
            extra={
                "alias": existing.alias,
                "phone_last4": customers.phone_last4(phone),
            },
        )

    customer = Customer(
        business_id=sale.business_id,
        phone=phone,
        alias=alias,
        consent_at=now_utc(),
        consent_version=settings.PRIVACY_POLICY_VERSION,
    )
    db.add(customer)
    await db.flush()
    await emit_event(
        db,
        business_id=sale.business_id,
        type="customer_created",
        actor="customer",
        actor_id=customer.id,
        customer_id=customer.id,
        sale_id=sale.id,
    )
    token = await customers.create_customer_session(db, customer, user_agent)
    result = await link_sale_to_customer(
        db, sale, customer, "qr", "customer", customer.id
    )
    return result, token


async def identify_confirm(
    db: AsyncSession, *, phone: str, claim_token: str, user_agent: str | None
) -> tuple[ClaimResult, str]:
    """Existing customer without a session confirms identity with a valid token (F3)."""
    phone = normalize_phone(phone)
    sale = await lock_sale_by_token(db, claim_token)
    validate_claimable(sale, "qr")
    customer = (
        await db.execute(
            select(Customer).where(
                Customer.business_id == sale.business_id, Customer.phone == phone
            )
        )
    ).scalar_one_or_none()
    if customer is None:
        raise AppError("customer_not_found")
    token = await customers.create_customer_session(db, customer, user_agent)
    await emit_event(
        db,
        business_id=sale.business_id,
        type="identity_confirmed",
        actor="customer",
        actor_id=customer.id,
        customer_id=customer.id,
        sale_id=sale.id,
    )
    result = await link_sale_to_customer(
        db, sale, customer, "qr", "customer", customer.id
    )
    return result, token


async def claim_with_session(
    db: AsyncSession, customer: Customer, claim_token: str
) -> ClaimResult:
    """F2: customer with an open session scans the QR."""
    sale = await lock_sale_by_token(db, claim_token)
    return await link_sale_to_customer(
        db, sale, customer, "qr", "customer", customer.id
    )
