from datetime import datetime
from uuid import UUID

from app.schemas.common import Schema
from app.schemas.sale import SaleCustomerOut


class SpinBrief(Schema):
    id: UUID
    reason: str
    milestone_n: int | None


class CardPrizeOut(Schema):
    id: UUID
    name: str
    short_label: str
    type: str
    awarded_at: datetime
    expires_at: datetime


class CardOut(Schema):
    """build_card() (11.7)."""

    customer: SaleCustomerOut
    purchases: int
    milestone_every: int
    progress: int
    purchases_to_next_spin: int
    available_spins: list[SpinBrief]
    active_prizes: list[CardPrizeOut]


class ClaimResultOut(Schema):
    card: CardOut
    counted: bool
    new_spins: list[SpinBrief]
    # False: the sale has no product that earns stamps (counted is then false too).
    stamp_eligible: bool
