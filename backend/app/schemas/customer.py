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


class CustomerDetailOut(Schema):
    id: UUID
    alias: str
    phone_last4: str
    purchases: int
    milestone_every: int
    active_prizes: list[CardPrizeOut]
    sales: list[CustomerSaleBrief]
