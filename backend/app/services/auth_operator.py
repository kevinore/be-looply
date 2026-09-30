from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import (
    OPERATOR_SESSION_DAYS,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)
from app.core.time import now_utc
from app.models import Business, Operator, OperatorSession
from app.services.events import emit_event

# Used when the email does not exist, so response time does not reveal it (11.1 step 3).
_DUMMY_HASH = hash_password("dummy-password-for-constant-time")


@dataclass
class OperatorContext:
    operator: Operator
    business: Business
    session: OperatorSession


async def login(
    db: AsyncSession, email: str, password: str, user_agent: str | None
) -> tuple[OperatorContext, str]:
    """Returns the context and the raw session token (only its hash is stored)."""
    email = email.strip().lower()
    operator = (
        await db.execute(
            select(Operator).where(Operator.email == email, Operator.active.is_(True))
        )
    ).scalar_one_or_none()
    if operator is None:
        verify_password(password, _DUMMY_HASH)
        raise AppError("invalid_credentials")
    if not verify_password(password, operator.password_hash):
        raise AppError("invalid_credentials")

    token = new_token()
    session = OperatorSession(
        operator_id=operator.id,
        token_hash=hash_token(token),
        user_agent=user_agent,
        expires_at=now_utc() + timedelta(days=OPERATOR_SESSION_DAYS),
    )
    db.add(session)
    await db.flush()
    business = await db.get(Business, operator.business_id)
    await emit_event(
        db,
        business_id=operator.business_id,
        type="operator_logged_in",
        actor="operator",
        actor_id=operator.id,
    )
    return OperatorContext(operator, business, session), token


async def logout(db: AsyncSession, ctx: OperatorContext) -> None:
    session = await db.get(OperatorSession, ctx.session.id)
    session.revoked_at = now_utc()
    await db.flush()


async def operator_from_token(db: AsyncSession, token: str) -> OperatorContext | None:
    row = (
        await db.execute(
            select(OperatorSession, Operator, Business)
            .join(Operator, Operator.id == OperatorSession.operator_id)
            .join(Business, Business.id == Operator.business_id)
            .where(
                OperatorSession.token_hash == hash_token(token),
                OperatorSession.revoked_at.is_(None),
                OperatorSession.expires_at > now_utc(),
                Operator.active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    session, operator, business = row
    return OperatorContext(operator, business, session)
