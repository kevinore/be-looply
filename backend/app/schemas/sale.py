from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import Schema

PaymentMethod = Literal["cash", "nequi", "breb", "card"]


class SaleItemIn(Schema):
    product_id: UUID
    qty: int = Field(ge=1, le=20)


class SaleCreateIn(Schema):
    """R3: products and quantities only. Any price sent by the client is ignored."""

    items: list[SaleItemIn] = Field(min_length=1, max_length=30)
    payment_method: PaymentMethod
    customer_id: UUID | None = None
    prize_award_id: UUID | None = None
    prize_target_product_id: UUID | None = None

    @model_validator(mode="after")
    def check(self):
        ids = [item.product_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("repeated product_id")
        if self.prize_award_id is not None and (
            self.customer_id is None or self.prize_target_product_id is None
        ):
            raise ValueError(
                "prize_award_id needs customer_id and prize_target_product_id"
            )
        return self


class SaleItemOut(Schema):
    product_id: UUID | None
    label: str
    qty: int
    unit_price_cop: int
    discount_cop: int
    prize_award_id: UUID | None


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
