from datetime import date, datetime
from uuid import UUID

from app.schemas.common import Schema
from app.schemas.sale import SaleCustomerOut, SaleItemOptionOut


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


class WorkdaySaleItemOut(Schema):
    label: str
    qty: int
    unit_price_cop: int
    discount_cop: int
    is_prize: bool
    options: list[SaleItemOptionOut]


class WorkdaySaleOut(Schema):
    """One sale of a workday, with its lines (void sales included)."""

    id: UUID
    paid_at: datetime
    status: str
    payment_method: str
    total_cop: int
    claim_method: str | None
    void_reason: str | None
    customer: SaleCustomerOut | None
    items: list[WorkdaySaleItemOut]


class WorkdaySalesPageOut(Schema):
    """One page of a workday's sales, newest first."""

    items: list[WorkdaySaleOut]
    # Pass as ?cursor= for the next page; null on the last page.
    next_cursor: str | None
    # Whole workday, not just this page.
    total: int
    voided: int
