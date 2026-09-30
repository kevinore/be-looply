from datetime import date, datetime
from uuid import UUID

from app.schemas.common import Schema


class WorkdayOut(Schema):
    id: UUID
    local_date: date
    day_type: str
    status: str
    opened_at: datetime
    opened_by: UUID
    closed_at: datetime | None
    weather_temp_c: float | None
    weather_code: int | None


class WorkdaySummaryOut(Schema):
    """One row of v_workday_summary."""

    workday_id: UUID
    local_date: date
    day_type: str
    status: str
    opened_at: datetime
    closed_at: datetime | None
    weather_temp_c: float | None
    weather_code: int | None
    sales: int
    claimed_sales: int
    revenue_cop: int
    cash_cop: int
    digital_cop: int
    drinks: int
