from fastapi import APIRouter

from app.api.deps import CurrentOperator, CurrentOwner
from app.core.db import DbSession
from app.schemas.prize import CatalogPrizeOut, PendingPrizeOut
from app.services import prizes
from app.services.prizes import PendingFilter

router = APIRouter(prefix="/api/op/prizes", tags=["op: prizes"])


@router.get("/pending", response_model=list[PendingPrizeOut])
async def pending(ctx: CurrentOperator, db: DbSession, filter: PendingFilter = "all"):
    return await prizes.pending_prizes(db, ctx.business.id, filter)


@router.get("/catalog", response_model=list[CatalogPrizeOut])
async def catalog(ctx: CurrentOwner, db: DbSession):
    return await prizes.catalog(db, ctx.business.id)
