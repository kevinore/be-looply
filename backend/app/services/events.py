from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event

# Section 14.4
OPERATOR_EVENT_TYPES = frozenset(
    {
        "operator_logged_in",
        "workday_opened",
        "workday_closed",
        "sale_paid",
        "sale_qr_shown",
        "sale_skipped",
        "sale_linked_manual",
        "sale_unlinked",
        "sale_voided",
        "prize_redeemed",
        "prize_restored",
        "void_left_redeemed_prize",
    }
)
CUSTOMER_EVENT_TYPES = frozenset(
    {
        "qr_scanned",
        "page_loaded",
        "register_viewed",
        "identity_rejected",
        "identity_confirmed",
        "customer_created",
        "card_viewed",
        "install_prompt_shown",
        "install_prompt_accepted",
        "sale_claimed",
        "spin_started",
        "prize_awarded",
    }
)
SYSTEM_EVENT_TYPES = frozenset({"spin_unlocked", "spin_voided", "prize_voided"})

EVENT_TYPES = OPERATOR_EVENT_TYPES | CUSTOMER_EVENT_TYPES | SYSTEM_EVENT_TYPES

Actor = Literal["customer", "operator", "system"]


def jsonable(row: dict) -> dict:
    """Make a DB row safe for a jsonb payload (Decimal, dates and UUIDs)."""
    out = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, (date, datetime)):
            value = value.isoformat()
        elif isinstance(value, UUID):
            value = str(value)
        out[key] = value
    return out


async def emit_event(
    db: AsyncSession,
    *,
    business_id: UUID,
    type: str,
    actor: Actor,
    actor_id: UUID | None = None,
    customer_id: UUID | None = None,
    sale_id: UUID | None = None,
    workday_id: UUID | None = None,
    payload: dict | None = None,
    client_ts: datetime | None = None,
) -> None:
    """R20: insert the event in the caller's session and transaction. Never commits."""
    if type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type: {type!r}")
    db.add(
        Event(
            business_id=business_id,
            type=type,
            actor=actor,
            actor_id=actor_id,
            customer_id=customer_id,
            sale_id=sale_id,
            workday_id=workday_id,
            payload=payload or {},
            client_ts=client_ts,
        )
    )
    await db.flush()
