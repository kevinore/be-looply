from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import for_update
from app.core.errors import AppError
from app.core.time import day_type, local_today, now_utc
from app.models import Business, Operator, Sale, Workday
from app.services import weather
from app.services.events import emit_event, jsonable
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
) -> Workday:
    local_date = local_today(business.timezone)
    existing = await current_workday(db, business.id)
    if existing is not None:
        raise AppError("workday_already_open", extra={"workday_id": str(existing.id)})
    closed_today = (
        await db.execute(
            select(Workday.id).where(
                Workday.business_id == business.id, Workday.local_date == local_date
            )
        )
    ).scalar_one_or_none()
    if closed_today is not None:
        raise AppError("workday_already_closed_today")

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
