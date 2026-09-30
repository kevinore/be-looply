from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import CUSTOMER_SESSION_DAYS, hash_token, new_token
from app.core.time import now_utc
from app.models import (
    Business,
    Customer,
    CustomerSession,
    PrizeAward,
    PrizeCatalog,
    Sale,
)


@dataclass
class CustomerContext:
    customer: Customer
    business: Business
    session: CustomerSession


def phone_last4(phone: str) -> str:
    """Customer responses only ever show the last 4 digits."""
    return phone[-4:]


async def purchases(db: AsyncSession, customer_id: UUID) -> int:
    """R8: counted purchases = distinct workdays with a claimed sale."""
    return (
        await db.execute(
            text(
                "SELECT purchases FROM v_customer_purchases "
                "WHERE customer_id = :customer_id"
            ),
            {"customer_id": customer_id},
        )
    ).scalar_one()


async def active_prizes(
    db: AsyncSession, customer_id: UUID
) -> list[tuple[PrizeAward, PrizeCatalog]]:
    """Prizes with status 'active' that have not expired, soonest expiry first."""
    rows = await db.execute(
        select(PrizeAward, PrizeCatalog)
        .join(PrizeCatalog, PrizeCatalog.id == PrizeAward.prize_id)
        .where(
            PrizeAward.customer_id == customer_id,
            PrizeAward.status == "active",
            PrizeAward.expires_at > now_utc(),
        )
        .order_by(PrizeAward.expires_at)
    )
    return [(award, prize) for award, prize in rows.all()]


async def get_customer(
    db: AsyncSession, business_id: UUID, customer_id: UUID
) -> Customer:
    customer = (
        await db.execute(
            select(Customer).where(
                Customer.id == customer_id, Customer.business_id == business_id
            )
        )
    ).scalar_one_or_none()
    if customer is None:
        raise AppError("customer_not_found")
    return customer


async def create_customer_session(
    db: AsyncSession, customer: Customer, user_agent: str | None
) -> str:
    """Returns the raw token for the cookie; only its hash is stored."""
    token = new_token()
    db.add(
        CustomerSession(
            customer_id=customer.id,
            token_hash=hash_token(token),
            user_agent=user_agent,
            expires_at=now_utc() + timedelta(days=CUSTOMER_SESSION_DAYS),
        )
    )
    await db.flush()
    return token


async def customer_from_token(db: AsyncSession, token: str) -> CustomerContext | None:
    row = (
        await db.execute(
            select(CustomerSession, Customer, Business)
            .join(Customer, Customer.id == CustomerSession.customer_id)
            .join(Business, Business.id == Customer.business_id)
            .where(
                CustomerSession.token_hash == hash_token(token),
                CustomerSession.revoked_at.is_(None),
                CustomerSession.expires_at > now_utc(),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    session, customer, business = row
    return CustomerContext(customer, business, session)


async def search_by_last4(
    db: AsyncSession, business_id: UUID, last4: str
) -> list[dict]:
    """Operator search (11.6): up to 10 customers whose phone ends in last4."""
    active_count = (
        select(func.count())
        .where(
            PrizeAward.customer_id == Customer.id,
            PrizeAward.status == "active",
            PrizeAward.expires_at > now_utc(),
        )
        .scalar_subquery()
    )
    rows = await db.execute(
        select(Customer, active_count)
        .where(
            Customer.business_id == business_id,
            func.right(Customer.phone, 4) == last4,
        )
        .order_by(Customer.alias)
        .limit(10)
    )
    return [
        {
            "id": customer.id,
            "alias": customer.alias,
            "phone_last4": phone_last4(customer.phone),
            "purchases": await purchases(db, customer.id),
            "active_prizes_count": count,
        }
        for customer, count in rows.all()
    ]


async def recent_sales(db: AsyncSession, customer_id: UUID, limit: int) -> list[Sale]:
    return list(
        (
            await db.execute(
                select(Sale)
                .where(Sale.customer_id == customer_id)
                .order_by(Sale.paid_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
