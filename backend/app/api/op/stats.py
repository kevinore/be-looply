from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentOperator, CurrentOwner
from app.core.db import DbSession
from app.schemas.stats import HistoryStatsOut, WorkdayStatsOut
from app.services import stats

router = APIRouter(prefix="/api/op", tags=["op: stats"])

DateFrom = Annotated[date, Query(alias="from")]
DateTo = Annotated[date, Query(alias="to")]


@router.get("/stats/workdays/{workday_id}", response_model=WorkdayStatsOut)
async def workday_stats(workday_id: UUID, ctx: CurrentOperator, db: DbSession):
    return await stats.workday_stats(db, ctx.business.id, workday_id)


@router.get("/stats/history", response_model=HistoryStatsOut)
async def history(
    date_from: DateFrom, date_to: DateTo, ctx: CurrentOperator, db: DbSession
):
    return await stats.history_stats(db, ctx.business.id, date_from, date_to)


@router.get("/export/sales.csv", response_class=Response)
async def export_sales(
    date_from: DateFrom, date_to: DateTo, ctx: CurrentOwner, db: DbSession
):
    content = await stats.export_sales_csv(db, ctx.business.id, date_from, date_to)
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="sales_{date_from}_{date_to}.csv"'
        },
    )
