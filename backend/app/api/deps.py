from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request, Response

from app.core.config import settings
from app.core.db import DbSession
from app.core.errors import AppError, error_response
from app.core.security import OPERATOR_COOKIE
from app.services.auth_operator import OperatorContext, operator_from_token

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def origin_check_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """CSRF protection (10.5). Together with SameSite=Lax cookies, this is enough."""
    if request.method in WRITE_METHODS:
        origin = request.headers.get("origin")
        if origin is not None and origin not in settings.ALLOWED_ORIGINS:
            return error_response("forbidden_origin")
        content_type = request.headers.get("content-type", "")
        if content_type.split(";")[0].strip().lower() != "application/json":
            return error_response("forbidden_origin")
    return await call_next(request)


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
