from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentOperator
from app.core.db import DbSession
from app.schemas.customer import CustomerDetailOut, CustomerSearchOut
from app.services import customers

router = APIRouter(prefix="/api/admin/customers", tags=["admin: customers"])


@router.get("/search", response_model=list[CustomerSearchOut])
async def search(
    last4: Annotated[str, Query(pattern=r"^[0-9]{4}$")],
    ctx: CurrentOperator,
    db: DbSession,
):
    return await customers.search_by_last4(db, ctx.business.id, last4)


@router.get("/{customer_id}", response_model=CustomerDetailOut)
async def detail(customer_id: UUID, ctx: CurrentOperator, db: DbSession):
    customer = await customers.get_customer(db, ctx.business.id, customer_id)
    return {
        "id": customer.id,
        "alias": customer.alias,
        "phone_last4": customers.phone_last4(customer.phone),
        "purchases": await customers.purchases(db, customer.id),
        "milestone_every": ctx.business.milestone_every,
        "active_prizes": [
            {
                "id": award.id,
                "name": prize.name,
                "short_label": prize.short_label,
                "type": prize.type,
                "awarded_at": award.awarded_at,
                "expires_at": award.expires_at,
                "value": prize.value,
                "max_value_cop": prize.max_value_cop,
                "category_id": prize.category_id,
            }
            for award, prize in await customers.active_prizes(db, customer.id)
        ],
        "sales": await customers.recent_sales(db, customer.id, 20),
    }
