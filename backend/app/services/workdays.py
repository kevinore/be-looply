import base64
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import for_update
from app.core.errors import AppError
from app.core.time import day_type, end_of_local_day, local_today, now_utc
from app.models import Business, Customer, Operator, Sale, SaleItem, Workday
from app.services import weather
from app.services.customers import phone_last4
from app.services.events import emit_event, jsonable
from app.services.options import options_by_item
from app.services.stats import workday_summary


async def current_workday(db: AsyncSession, business_id: UUID) -> Workday | None:
    return (
        await db.execute(
            select(Workday).where(
                Workday.business_id == business_id, Workday.status == "open"
            )
        )
    ).scalar_one_or_none()


async def require_open_workday(
    db: AsyncSession, business_id: UUID, *, lock: bool = False
) -> Workday:
    """Cross-cutting rule (11.2): creating sales, linking and redeeming need an open workday."""
    stmt = select(Workday).where(
        Workday.business_id == business_id, Workday.status == "open"
    )
    workday = (
        await db.execute(for_update(stmt) if lock else stmt)
    ).scalar_one_or_none()
    if workday is None:
        raise AppError("workday_not_open")
    return workday


async def open_workday(
    db: AsyncSession, business: Business, operator: Operator
) -> tuple[Workday, bool]:
    """Open today's workday. Returns (workday, reopened).

    One workday per local date: if today's was already closed, it is reopened, so
    every sale of the day stays grouped under the same workday.
    """
    local_date = local_today(business.timezone)
    existing = await current_workday(db, business.id)
    if existing is not None:
        raise AppError("workday_already_open", extra={"workday_id": str(existing.id)})
    today = (
        await db.execute(
            for_update(
                select(Workday).where(
                    Workday.business_id == business.id, Workday.local_date == local_date
                )
            )
        )
    ).scalar_one_or_none()
    if today is not None:
        return await reopen_workday(db, business, operator, today), True

    # If the weather API fails, open without weather.
    temp_c, code = await weather.current_weather(business.latitude, business.longitude)
    kind = day_type(local_date)
    workday = Workday(
        business_id=business.id,
        local_date=local_date,
        day_type=kind,
        opened_by=operator.id,
        weather_temp_c=temp_c,
        weather_code=code,
    )
    db.add(workday)
    await db.flush()
    await db.refresh(workday)
    await emit_event(
        db,
        business_id=business.id,
        type="workday_opened",
        actor="operator",
        actor_id=operator.id,
        workday_id=workday.id,
        payload={"weather_temp_c": temp_c, "weather_code": code, "day_type": kind},
    )
    return workday, False


async def reopen_workday(
    db: AsyncSession, business: Business, operator: Operator, workday: Workday
) -> Workday:
    """Reopen today's closed workday (the caller holds its lock). Sales stay in it."""
    if workday.status == "open":  # another request reopened it first
        raise AppError("workday_already_open", extra={"workday_id": str(workday.id)})
    closed_at = workday.closed_at
    workday.status = "open"
    workday.closed_at = None
    workday.closed_by = None
    # R7: closing expired the pending QR codes; the same workday continues, so
    # they are valid again until the end of the local day.
    await db.execute(
        update(Sale)
        .where(Sale.workday_id == workday.id, Sale.status == "paid")
        .values(claim_expires_at=end_of_local_day(business.timezone))
    )
    await db.flush()
    await db.refresh(workday)
    await emit_event(
        db,
        business_id=business.id,
        type="workday_reopened",
        actor="operator",
        actor_id=operator.id,
        workday_id=workday.id,
        payload={"previous_closed_at": closed_at.isoformat() if closed_at else None},
    )
    return workday


async def close_workday(
    db: AsyncSession, business: Business, operator: Operator
) -> dict:
    workday = await require_open_workday(db, business.id, lock=True)
    now = now_utc()
    workday.status = "closed"
    workday.closed_at = now
    workday.closed_by = operator.id
    # R7: pending QR codes expire when the workday closes.
    await db.execute(
        update(Sale)
        .where(
            Sale.workday_id == workday.id,
            Sale.status == "paid",
            Sale.claim_expires_at > now,
        )
        .values(claim_expires_at=now)
    )
    await db.flush()
    summary = await workday_summary(db, business.id, workday.id)
    await emit_event(
        db,
        business_id=business.id,
        type="workday_closed",
        actor="operator",
        actor_id=operator.id,
        workday_id=workday.id,
        payload=jsonable(summary),
    )
    return summary


def encode_cursor(sale: Sale) -> str:
    raw = f"{sale.paid_at.isoformat()}|{sale.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        paid_at, sale_id = raw.split("|")
        return datetime.fromisoformat(paid_at), UUID(sale_id)
    except ValueError:
        raise AppError("validation_error") from None


async def workday_sales(
    db: AsyncSession,
    business_id: UUID,
    workday_id: UUID,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """A page of the sales of a workday of this business (R21), newest first.

    Keyset pagination on (paid_at, id): stable while new sales arrive.
    """
    workday = (
        await db.execute(
            select(Workday.id).where(
                Workday.id == workday_id, Workday.business_id == business_id
            )
        )
    ).scalar_one_or_none()
    if workday is None:
        raise AppError("workday_not_found")
    total, voided = (
        await db.execute(
            select(
                func.count().filter(Sale.status != "void"),
                func.count().filter(Sale.status == "void"),
            ).where(Sale.workday_id == workday_id)
        )
    ).one()
    stmt = select(Sale).where(Sale.workday_id == workday_id)
    if cursor:
        paid_at, sale_id = decode_cursor(cursor)
        stmt = stmt.where(tuple_(Sale.paid_at, Sale.id) < tuple_(paid_at, sale_id))
    sales = list(
        (
            await db.execute(
                stmt.order_by(Sale.paid_at.desc(), Sale.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(sales) > limit
    sales = sales[:limit]
    page = {
        "items": [],
        "next_cursor": encode_cursor(sales[-1]) if has_more else None,
        "total": total,
        "voided": voided,
    }
    if not sales:
        return page
    ids = [s.id for s in sales]
    lines = list(
        (
            await db.execute(
                select(SaleItem)
                .where(SaleItem.sale_id.in_(ids))
                .order_by(SaleItem.created_at)
            )
        ).scalars()
    )
    chosen = await options_by_item(db, [i.id for i in lines])
    items: dict[UUID, list[dict]] = {}
    for item in lines:
        items.setdefault(item.sale_id, []).append(
            {
                "label": item.label,
                "qty": item.qty,
                "unit_price_cop": item.unit_price_cop,
                "discount_cop": item.discount_cop,
                "is_prize": item.prize_award_id is not None,
                "options": chosen.get(item.id, []),
            }
        )
    customer_ids = {s.customer_id for s in sales if s.customer_id}
    customers = {
        c.id: c
        for c in (
            await db.execute(select(Customer).where(Customer.id.in_(customer_ids)))
        ).scalars()
    }
    page["items"] = [
        {
            "id": s.id,
            "paid_at": s.paid_at,
            "status": s.status,
            "payment_method": s.payment_method,
            "total_cop": s.total_cop,
            "claim_method": s.claim_method,
            "void_reason": s.void_reason,
            "customer": (
                {
                    "id": c.id,
                    "alias": c.alias,
                    "phone_last4": phone_last4(c.phone),
                }
                if (c := customers.get(s.customer_id))
                else None
            ),
            "items": items.get(s.id, []),
        }
        for s in sales
    ]
    return page
