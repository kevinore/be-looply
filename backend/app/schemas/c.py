"""Customer app (/api/c/*). Phone numbers only ever appear as phone_last4."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.card import CardOut
from app.schemas.common import Schema


class PublicBusinessOut(Schema):
    name: str
    slug: str
    branding: dict
    privacy_policy_version: str


class PreviewSale(Schema):
    items_count: int
    total_cop: int
    paid_at: datetime


class PreviewBusiness(Schema):
    name: str
    branding: dict


class ClaimPreviewOut(Schema):
    state: Literal["claimable", "already_claimed", "expired", "voided", "not_found"]
    sale: PreviewSale | None
    business: PreviewBusiness | None


class RegisterIn(Schema):
    phone: str
    alias: str
    consent: bool
    claim_token: str


class IdentifyIn(Schema):
    phone: str
    claim_token: str


class ClaimIn(Schema):
    claim_token: str


class HistoryItem(Schema):
    label: str
    qty: int
    unit_price_cop: int
    discount_cop: int


class HistorySale(Schema):
    id: UUID
    paid_at: datetime
    items: list[HistoryItem]
    total_cop: int
    prize_used: str | None


class WheelSegment(Schema):
    id: UUID
    short_label: str
    color: str | None


class WheelOut(Schema):
    segments: list[WheelSegment]


class AwardBrief(Schema):
    id: UUID
    name: str
    short_label: str
    type: str
    expires_at: datetime


class SpinResultOut(Schema):
    segment_index: int | None
    prize_award: AwardBrief
    card: CardOut


class PrizeDetailOut(Schema):
    id: UUID
    name: str
    short_label: str
    type: str
    status: Literal["active", "redeemed", "void", "expired"]
    awarded_at: datetime
    expires_at: datetime
    redeemed_at: datetime | None


class EventIn(Schema):
    type: str
    sale_id: UUID | None = None
    payload: dict = Field(default_factory=dict)
    client_ts: datetime | None = None
