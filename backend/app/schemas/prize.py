from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas.common import Schema

PrizeType = Literal["percent_off", "free_item", "extra_item"]


class PendingPrizeOut(Schema):
    """One row of v_pending_prizes."""

    prize_award_id: UUID
    customer_id: UUID
    alias: str
    phone_last4: str
    prize_name: str
    prize_type: str
    awarded_at: datetime
    expires_at: datetime


class CatalogPrizeOut(Schema):
    """Owner only: includes weights."""

    id: UUID
    name: str
    short_label: str
    type: str
    value: int
    max_value_cop: int | None
    # R17: the prize applies only to products of this category; null = any.
    category_id: UUID | None
    weight: int
    expires_days: int
    color: str | None
    sort_order: int
    active: bool
    # Already won at least once: type, value, max_value_cop and category_id can no
    # longer change.
    awarded: bool


class WheelPrizeIn(Schema):
    """One prize of the wheel editor. No id = a new prize."""

    id: UUID | None = None
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)
    ]
    short_label: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=14)
    ]
    type: PrizeType
    value: int = Field(0, ge=0, le=100)
    max_value_cop: int | None = Field(None, gt=0)
    category_id: UUID | None = None
    # Chance of winning in hundredths of a percent (2.5% = 250).
    weight: int = Field(ge=1, le=10_000)
    expires_days: int = Field(ge=1, le=365)
    color: Annotated[
        str | None,
        StringConstraints(pattern=r"^(primary|secondary|ink|#[0-9A-Fa-f]{6})$"),
    ] = None
    active: bool


class WheelIn(Schema):
    """The whole wheel, in display order. Every existing prize must be listed."""

    prizes: list[WheelPrizeIn] = Field(min_length=1, max_length=50)
