from datetime import datetime
from uuid import UUID

from app.schemas.common import Schema


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
    weight: int
    expires_days: int
    color: str | None
    sort_order: int
    active: bool
