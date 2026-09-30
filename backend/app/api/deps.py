import random
import secrets
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy import select

from app.core.config import settings
from app.core.db import DbSession
from app.core.errors import AppError, error_response
from app.core.security import CUSTOMER_COOKIE, OPERATOR_COOKIE
from app.models import Business
from app.services.auth_operator import OperatorContext, operator_from_token
from app.services.customers import CustomerContext, customer_from_token

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def origin_check_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """CSRF protection (10.5). Together with SameSite=Lax cookies, this is enough."""
    if request.method in WRITE_METHODS:
        origin = request.headers.get("origin")
        if origin is not None and origin not in settings.ALLOWED_ORIGINS:
            return error_response("forbidden_origin")
        # Owner decision: JSON is only required when there is a body. A body-less
        # request carries no data, and the Origin check above still applies.
        content_type = request.headers.get("content-type", "")
        if has_body(request) and (
            content_type.split(";")[0].strip().lower() != "application/json"
        ):
            return error_response("forbidden_origin")
    return await call_next(request)


def has_body(request: Request) -> bool:
    if "transfer-encoding" in request.headers:
        return True
    length = request.headers.get("content-length", "0").strip()
    return not (length.isdigit() and int(length) == 0)


async def get_current_operator(request: Request, db: DbSession) -> OperatorContext:
    """Required by every /api/op/* endpoint except login (11.1)."""
    token = request.cookies.get(OPERATOR_COOKIE)
    if not token:
        raise AppError("not_authenticated")
    # Own short transaction, so write endpoints can open theirs afterwards.
    async with db.begin():
        ctx = await operator_from_token(db, token)
    if ctx is None:
        raise AppError("not_authenticated")
    return ctx


CurrentOperator = Annotated[OperatorContext, Depends(get_current_operator)]


async def require_owner(ctx: CurrentOperator) -> OperatorContext:
    if ctx.operator.role != "owner":
        raise AppError("forbidden")
    return ctx


CurrentOwner = Annotated[OperatorContext, Depends(require_owner)]


async def get_optional_customer(
    request: Request, db: DbSession
) -> CustomerContext | None:
    """Customer from the c_session cookie, or None (endpoints open to anonymous use)."""
    token = request.cookies.get(CUSTOMER_COOKIE)
    if not token:
        return None
    async with db.begin():
        return await customer_from_token(db, token)


OptionalCustomer = Annotated[CustomerContext | None, Depends(get_optional_customer)]


async def get_current_customer(ctx: OptionalCustomer) -> CustomerContext:
    if ctx is None:
        raise AppError("not_authenticated")
    return ctx


CurrentCustomer = Annotated[CustomerContext, Depends(get_current_customer)]


async def get_public_business(ctx: OptionalCustomer, db: DbSession) -> Business:
    """The customer's business if there is a session; otherwise DEFAULT_BUSINESS_SLUG."""
    if ctx is not None:
        return ctx.business
    async with db.begin():
        business = (
            await db.execute(
                select(Business).where(Business.slug == settings.DEFAULT_BUSINESS_SLUG)
            )
        ).scalar_one_or_none()
    if business is None:
        raise RuntimeError("DEFAULT_BUSINESS_SLUG does not match any business")
    return business


PublicBusiness = Annotated[Business, Depends(get_public_business)]


def get_rng() -> random.Random:
    """Prize draw generator (R12). Tests override it with a deterministic one."""
    return secrets.SystemRandom()


Rng = Annotated[random.Random, Depends(get_rng)]
