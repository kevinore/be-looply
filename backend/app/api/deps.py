from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.core.config import settings
from app.core.errors import error_response

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
