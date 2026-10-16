from datetime import datetime
from uuid import UUID

from app.schemas.card import CardPrizeOut
from app.schemas.common import Schema


class CustomerSearchOut(Schema):
    id: UUID
    alias: str
    phone_last4: str
    purchases: int
    active_prizes_count: int


class CustomerSaleBrief(Schema):
    id: UUID
    status: str
    total_cop: int
    payment_method: str
    paid_at: datetime


class OpCustomerPrizeOut(CardPrizeOut):
    """Active prize as seen by the operator: includes the catalog value so the
    sale screen can show an estimated discount (the sale still computes it)."""

    value: int
    max_value_cop: int | None
    # R17: the prize applies only to products of this category; null = any.
    category_id: UUID | None


class CustomerDetailOut(Schema):
    id: UUID
    alias: str
    phone_last4: str
    purchases: int
    milestone_every: int
    active_prizes: list[OpCustomerPrizeOut]
    sales: list[CustomerSaleBrief]
