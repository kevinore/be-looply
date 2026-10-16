from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentOperator
from app.core.db import DbSession
from app.schemas.workday import WorkdayOut, WorkdaySalesPageOut, WorkdaySummaryOut
from app.services import workdays

router = APIRouter(prefix="/api/admin/workdays", tags=["admin: workdays"])


@router.get("/current", response_model=WorkdayOut | None)
async def current(ctx: CurrentOperator, db: DbSession):
    return await workdays.current_workday(db, ctx.business.id)


@router.post("/open", response_model=WorkdayOut, status_code=201)
async def open_workday(response: Response, ctx: CurrentOperator, db: DbSession):
    """Opens today's workday, or reopens it (200) if it was closed earlier today."""
    async with db.begin():
        workday, reopened = await workdays.open_workday(db, ctx.business, ctx.operator)
    if reopened:
        response.status_code = 200
    return workday


@router.post("/current/close", response_model=WorkdaySummaryOut)
async def close_workday(ctx: CurrentOperator, db: DbSession):
    async with db.begin():
        return await workdays.close_workday(db, ctx.business, ctx.operator)


@router.get("/{workday_id}/sales", response_model=WorkdaySalesPageOut)
async def workday_sales(
    workday_id: UUID,
    ctx: CurrentOperator,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
):
    """Every sale of the workday, newest first, with lines and customer."""
    return await workdays.workday_sales(db, ctx.business.id, workday_id, limit, cursor)
