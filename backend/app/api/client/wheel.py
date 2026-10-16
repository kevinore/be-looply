from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentCustomer, PublicBusiness, Rng
from app.core.db import DbSession
from app.core.errors import AppError
from app.core.time import now_utc
from app.models import PrizeAward, PrizeCatalog
from app.schemas.c import PrizeDetailOut, SpinResultOut, WheelOut
from app.services import prizes, spins

router = APIRouter(prefix="/api/c", tags=["c: wheel"])


@router.get("/wheel", response_model=WheelOut)
async def wheel(biz: PublicBusiness, db: DbSession):
    """Active segments in sort_order, WITHOUT weights (R12)."""
    segments = await prizes.active_catalog(db, biz.id)
    return {
        "segments": [
            {"id": p.id, "short_label": p.short_label, "color": p.color}
            for p in segments
        ]
    }


@router.post("/spins/{spin_id}/spin", response_model=SpinResultOut)
async def spin(spin_id: UUID, ctx: CurrentCustomer, db: DbSession, rng: Rng):
    async with db.begin():
        return await spins.spin(db, ctx.customer, spin_id, rng)


@router.get("/prizes/{prize_award_id}", response_model=PrizeDetailOut)
async def prize_detail(prize_award_id: UUID, ctx: CurrentCustomer, db: DbSession):
    row = (
        await db.execute(
            select(PrizeAward, PrizeCatalog)
            .join(PrizeCatalog, PrizeCatalog.id == PrizeAward.prize_id)
            .where(
                PrizeAward.id == prize_award_id,
                PrizeAward.customer_id == ctx.customer.id,
            )
        )
    ).one_or_none()
    if row is None:
        raise AppError("prize_not_found")
    award, prize = row
    status = award.status
    # "Expired" is computed, never stored.
    if status == "active" and award.expires_at <= now_utc():
        status = "expired"
    return {
        "id": award.id,
        "name": prize.name,
        "short_label": prize.short_label,
        "type": prize.type,
        "status": status,
        "awarded_at": award.awarded_at,
        "expires_at": award.expires_at,
        "redeemed_at": award.redeemed_at,
    }
