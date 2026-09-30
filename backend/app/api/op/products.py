from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentOperator
from app.core.db import DbSession
from app.models import Product
from app.schemas.product import ProductOut

router = APIRouter(prefix="/api/op/products", tags=["op: products"])


@router.get("", response_model=list[ProductOut])
async def list_products(ctx: CurrentOperator, db: DbSession):
    """Active products of the business, by sort_order (11.4)."""
    return (
        (
            await db.execute(
                select(Product)
                .where(Product.business_id == ctx.business.id, Product.active.is_(True))
                .order_by(Product.sort_order, Product.name)
            )
        )
        .scalars()
        .all()
    )
