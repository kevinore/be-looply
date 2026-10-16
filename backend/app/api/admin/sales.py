from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Response
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentOperator
from app.core.db import DbSession
from app.core.errors import AppError, constraint_name
from app.schemas.card import ClaimResultOut
from app.schemas.sale import (
    LinkIn,
    RedeemPrizeIn,
    SaleCreateIn,
    SaleOut,
    SaleStatusOut,
    VoidIn,
)
from app.services import prizes, sales, voids
from app.services.claims import ClaimResult

router = APIRouter(prefix="/api/admin/sales", tags=["admin: sales"])


def claim_result_out(result: ClaimResult) -> dict:
    return {
        "card": result.card,
        "counted": result.counted,
        "new_spins": result.new_spins,
        "stamp_eligible": result.stamp_eligible,
    }


def parse_idempotency_key(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise AppError("validation_error") from None


@router.post("", response_model=SaleOut, status_code=201)
async def create_sale(
    body: SaleCreateIn,
    response: Response,
    ctx: CurrentOperator,
    db: DbSession,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
):
    key = parse_idempotency_key(idempotency_key)
    # A rollback expires every object in the session (ctx included): keep the id.
    business_id = ctx.business.id
    try:
        async with db.begin():
            sale, created = await sales.create_sale(db, ctx, body, key)
            detail = await sales.sale_detail(db, sale)
    except IntegrityError as exc:
        # 11.5 step 13: a concurrent request with the same key won the race.
        if constraint_name(exc) != "sale_idempotency_key_key":
            raise
        async with db.begin():
            sale = await sales.find_by_idempotency_key(db, business_id, key)
            created = False
            detail = await sales.sale_detail(db, sale)
    if not created:
        response.status_code = 200
    return detail


@router.get("/{sale_id}", response_model=SaleOut)
async def get_sale(sale_id: UUID, ctx: CurrentOperator, db: DbSession):
    sale = await sales.get_sale(db, ctx.business.id, sale_id)
    return await sales.sale_detail(db, sale)


@router.get("/{sale_id}/status", response_model=SaleStatusOut)
async def sale_status(sale_id: UUID, ctx: CurrentOperator, db: DbSession):
    sale = await sales.get_sale(db, ctx.business.id, sale_id)
    return await sales.sale_status(db, sale)


@router.post("/{sale_id}/link", response_model=ClaimResultOut)
async def link(sale_id: UUID, body: LinkIn, ctx: CurrentOperator, db: DbSession):
    async with db.begin():
        result = await sales.link_manual(db, ctx, sale_id, body.customer_id)
    return claim_result_out(result)


@router.post("/{sale_id}/unlink", response_model=SaleOut)
async def unlink(sale_id: UUID, ctx: CurrentOperator, db: DbSession):
    async with db.begin():
        sale = await sales.unlink(db, ctx, sale_id)
        return await sales.sale_detail(db, sale)


@router.post("/{sale_id}/void", response_model=SaleOut)
async def void(sale_id: UUID, body: VoidIn, ctx: CurrentOperator, db: DbSession):
    async with db.begin():
        sale = await voids.void_sale(db, sale_id, body.reason, ctx.operator)
        return await sales.sale_detail(db, sale)


@router.post("/{sale_id}/redeem-prize", response_model=SaleOut)
async def redeem_prize(
    sale_id: UUID, body: RedeemPrizeIn, ctx: CurrentOperator, db: DbSession
):
    async with db.begin():
        sale = await sales.lock_modifiable_sale(db, ctx, sale_id, "claimed")
        await prizes.redeem_on_paid_sale(
            db,
            sale,
            body.prize_award_id,
            body.product_id,
            ctx.operator,
            body.option_ids,
        )
        return await sales.sale_detail(db, sale)
