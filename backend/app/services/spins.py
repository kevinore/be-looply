import random
from uuid import UUID

import sentry_sdk
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import for_update
from app.core.errors import AppError
from app.core.time import now_utc
from app.models import Customer, PrizeAward, PrizeCatalog, Spin
from app.services import prizes
from app.services.claims import build_card
from app.services.events import emit_event


async def spin(
    db: AsyncSession, customer: Customer, spin_id: UUID, rng: random.Random
) -> dict:
    """R12: the server draws the prize. Spinning the same spin twice returns the same prize."""
    row = (
        await db.execute(
            for_update(
                select(Spin).where(Spin.id == spin_id, Spin.customer_id == customer.id)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError("spin_not_found")

    segments = await prizes.active_catalog(db, customer.business_id)

    if row.status == "consumed":
        award = (
            await db.execute(select(PrizeAward).where(PrizeAward.spin_id == row.id))
        ).scalar_one()
        prize = await db.get(PrizeCatalog, award.prize_id)
        return await _response(db, customer, segments, award, prize)
    if row.status == "void":
        raise AppError("spin_not_available")

    if not segments:
        sentry_sdk.capture_message("No active prizes to spin", level="error")
        raise AppError("internal_error")

    # Weighted draw among active prizes. Weights never leave the API.
    prize = rng.choices(segments, weights=[p.weight for p in segments], k=1)[0]
    award = await prizes.award_prize(
        db, row.id, customer.id, customer.business_id, prize
    )
    row.status = "consumed"
    row.spun_at = now_utc()
    await db.flush()

    common = {
        "business_id": customer.business_id,
        "actor": "customer",
        "actor_id": customer.id,
        "customer_id": customer.id,
        "sale_id": row.unlocked_by_sale_id,
    }
    await emit_event(
        db, type="spin_started", payload={"spin_id": str(row.id)}, **common
    )
    await emit_event(
        db,
        type="prize_awarded",
        payload={"spin_id": str(row.id), "prize_award_id": str(award.id)},
        **common,
    )
    return await _response(db, customer, segments, award, prize)


async def _response(
    db: AsyncSession,
    customer: Customer,
    segments: list[PrizeCatalog],
    award: PrizeAward,
    prize: PrizeCatalog,
) -> dict:
    ids = [p.id for p in segments]
    return {
        # Position of the prize in GET /api/client/wheel (None if no longer on the wheel).
        "segment_index": ids.index(prize.id) if prize.id in ids else None,
        "prize_award": {
            "id": award.id,
            "name": prize.name,
            "short_label": prize.short_label,
            "type": prize.type,
            "expires_at": award.expires_at,
        },
        "card": await build_card(db, customer),
    }
