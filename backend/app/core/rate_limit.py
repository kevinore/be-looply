from fastapi import Request
from limits import parse
from slowapi import Limiter

from app.core.errors import AppError

# Section 10.6
LOGIN_PER_EMAIL = "5/15minutes"
LOGIN_PER_IP = "20/15minutes"
CUSTOMER_AUTH_PER_IP = "10/10minutes"  # /api/c/register, /api/c/identify/confirm
CUSTOMER_AUTH_PER_TOKEN = "5/10minutes"
CLAIM_PREVIEW_PER_IP = "30/minute"  # GET /api/c/claims/{token}
EVENTS_PER_IP = "60/minute"  # POST /api/c/events, /api/op/events


def client_ip(request: Request) -> str:
    """First value of X-Forwarded-For; otherwise the connection IP."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


# In memory: a single instance runs on Railway.
limiter = Limiter(key_func=client_ip, storage_uri="memory://")


def enforce(limit: str, scope: str, key: str) -> None:
    """Count one hit for `key` under `scope`; raise rate_limited when over the limit."""
    if not limiter.limiter.hit(parse(limit), scope, key):
        raise AppError("rate_limited")


def reset() -> None:
    """Clear all counters (tests)."""
    limiter.reset()
