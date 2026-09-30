from fastapi import APIRouter

from app.api.deps import CurrentOperator
from app.core.db import DbSession
from app.schemas.workday import WorkdayOut, WorkdaySummaryOut
from app.services import workdays

router = APIRouter(prefix="/api/op/workdays", tags=["op: workdays"])


@router.get("/current", response_model=WorkdayOut | None)
async def current(ctx: CurrentOperator, db: DbSession):
    return await workdays.current_workday(db, ctx.business.id)


@router.post("/open", response_model=WorkdayOut, status_code=201)
async def open_workday(ctx: CurrentOperator, db: DbSession):
    async with db.begin():
        return await workdays.open_workday(db, ctx.business, ctx.operator)


@router.post("/current/close", response_model=WorkdaySummaryOut)
async def close_workday(ctx: CurrentOperator, db: DbSession):
    async with db.begin():
        return await workdays.close_workday(db, ctx.business, ctx.operator)
