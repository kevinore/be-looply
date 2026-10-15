from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import Schema

# Owner decision (2026-10-14): three methods. Old sales may still say "nequi" or
# "breb" (migration 0006), so responses keep payment_method as a plain string.
PaymentMethod = Literal["cash", "transfer", "card"]


class SaleItemIn(Schema):
    product_id: UUID
    qty: int = Field(ge=1, le=20)
    # Chosen options (services/options.py). The same product may appear in
    # several lines, one per combination of options.
    option_ids: list[UUID] = Field(default_factory=list, max_length=20)


class SaleCreateIn(Schema):
    """R3: products and quantities only. Any price sent by the client is ignored."""

    items: list[SaleItemIn] = Field(min_length=1, max_length=30)
    payment_method: PaymentMethod
    customer_id: UUID | None = None
    prize_award_id: UUID | None = None
    prize_target_product_id: UUID | None = None

    @model_validator(mode="after")
    def check(self):
        lines = [(i.product_id, frozenset(i.option_ids)) for i in self.items]
        if len(lines) != len(set(lines)):
            raise ValueError("repeated product_id with the same options")
        if self.prize_award_id is not None and (
            self.customer_id is None or self.prize_target_product_id is None
        ):
            raise ValueError(
                "prize_award_id needs customer_id and prize_target_product_id"
            )
        return self


class SaleItemOptionOut(Schema):
    group_name: str
    option_name: str
    price_delta_cop: int


class SaleItemOut(Schema):
    product_id: UUID | None
    label: str
    qty: int
    # Product price plus the price of its options.
    unit_price_cop: int
    discount_cop: int
    prize_award_id: UUID | None
    options: list[SaleItemOptionOut]


class SaleCustomerOut(Schema):
    id: UUID
    alias: str
    phone_last4: str


class SaleOut(Schema):
    id: UUID
    workday_id: UUID
    status: str
    total_cop: int
    payment_method: str
    items: list[SaleItemOut]
    claim_url: str
    claim_expires_at: datetime
    claim_method: str | None
    paid_at: datetime
    claimed_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None
    customer: SaleCustomerOut | None


class ActivePrizeBrief(Schema):
    id: UUID
    name: str
    type: str
    expires_at: datetime


class SaleStatusCustomerOut(SaleCustomerOut):
    purchases: int
    active_prizes: list[ActivePrizeBrief]


class SaleStatusOut(Schema):
    status: str
    customer: SaleStatusCustomerOut | None


class LinkIn(Schema):
    customer_id: UUID


class VoidIn(Schema):
    reason: str = Field(min_length=3, max_length=200)


class RedeemPrizeIn(Schema):
    prize_award_id: UUID
    product_id: UUID | None = None
    # Options of the free product, when it has option groups.
    option_ids: list[UUID] = Field(default_factory=list, max_length=20)
