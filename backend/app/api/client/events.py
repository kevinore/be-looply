from fastapi import APIRouter, Request, Response

from app.api.deps import OptionalCustomer, PublicBusiness
from app.core import rate_limit
from app.core.db import DbSession
from app.schemas.client import EventIn
from app.services.events import record_client_event

router = APIRouter(prefix="/api/client", tags=["client: events"])


@router.post("/events", status_code=204)
async def post_event(
    body: EventIn,
    request: Request,
    ctx: OptionalCustomer,
    biz: PublicBusiness,
    db: DbSession,
):
    rate_limit.enforce(
        rate_limit.EVENTS_PER_IP, "events_ip", rate_limit.client_ip(request)
    )
    async with db.begin():
        await record_client_event(
            db,
            app="customer",
            business_id=biz.id,
            actor_id=ctx.customer.id if ctx else None,
            type=body.type,
            sale_id=body.sale_id,
            payload=body.payload,
            client_ts=body.client_ts,
        )
    return Response(status_code=204)
