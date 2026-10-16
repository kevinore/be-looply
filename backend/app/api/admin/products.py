from fastapi import APIRouter

from app.api.deps import CurrentOperator
from app.core.db import DbSession
from app.schemas.product import ProductOut
from app.services import options

router = APIRouter(prefix="/api/op/products", tags=["op: products"])


@router.get("", response_model=list[ProductOut])
async def list_products(ctx: CurrentOperator, db: DbSession):
    """Active products of the business, by sort_order, with their options (11.4)."""
    return await options.catalog(db, ctx.business.id)
