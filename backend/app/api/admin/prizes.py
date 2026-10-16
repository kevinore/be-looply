from fastapi import APIRouter

from app.api.deps import CurrentOperator, CurrentOwner
from app.core.db import DbSession
from app.schemas.prize import CatalogPrizeOut, PendingPrizeOut, WheelIn
from app.services import prizes
from app.services.prizes import PendingFilter

router = APIRouter(prefix="/api/admin/prizes", tags=["admin: prizes"])


@router.get("/pending", response_model=list[PendingPrizeOut])
async def pending(ctx: CurrentOperator, db: DbSession, filter: PendingFilter = "all"):
    return await prizes.pending_prizes(db, ctx.business.id, filter)


@router.get("/catalog", response_model=list[CatalogPrizeOut])
async def catalog(ctx: CurrentOwner, db: DbSession):
    return await prizes.catalog(db, ctx.business.id)


@router.put("/catalog", response_model=list[CatalogPrizeOut])
async def save_catalog(body: WheelIn, ctx: CurrentOwner, db: DbSession):
    """Wheel editor: every prize in display order; active weights add up to 100%."""
    business_id = ctx.business.id
    async with db.begin():
        await prizes.save_wheel(db, business_id, ctx.operator, body.prizes)
        return await prizes.catalog(db, business_id)
