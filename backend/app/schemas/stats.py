from uuid import UUID

from app.schemas.common import Schema
from app.schemas.workday import WorkdaySummaryOut


class WorkdayRatesOut(WorkdaySummaryOut):
    drinks_per_sale: float
    claimed_pct: float


class HourlyOut(Schema):
    local_hour: int
    sales: int
    revenue_cop: int


class ProductStatsOut(Schema):
    product_id: UUID
    label: str
    units: int
    gross_cop: int
    discount_cop: int
    net_cop: int
    cost_incomplete: bool
    margin_cop: int | None


class OptionSalesOut(Schema):
    """Units sold with one option (e.g. the flavor "Coco"), by product category."""

    category: str | None
    group_name: str
    option_name: str
    units: int


class WorkdayStatsOut(Schema):
    summary: WorkdayRatesOut
    hourly: list[HourlyOut]
    top_products: list[ProductStatsOut]
    # Every product sold in the workday, most units first.
    products: list[ProductStatsOut]
    best_hour: int | None
    cost_incomplete: bool
    margin_cop: int | None
    # Options chosen (flavors, bases...), most units first.
    options: list[OptionSalesOut]


class HourlyAverageOut(Schema):
    local_hour: int
    avg_sales: float
    avg_revenue_cop: float


class HistoryStatsOut(Schema):
    workdays: list[WorkdayRatesOut]
    products: list[ProductStatsOut]
    hourly_average: list[HourlyAverageOut]
    cost_incomplete: bool
    margin_cop: int | None
