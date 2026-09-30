from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentCustomer, PublicBusiness
from app.core import rate_limit
from app.core.config import settings
from app.core.db import DbSession
from app.core.security import (
    CUSTOMER_COOKIE,
    CUSTOMER_SESSION_DAYS,
    clear_session_cookie,
    set_session_cookie,
)
from app.core.time import now_utc
from app.models import CustomerSession
from app.schemas.c import (
    ClaimIn,
    ClaimPreviewOut,
    HistorySale,
    IdentifyIn,
    PublicBusinessOut,
    RegisterIn,
)
from app.schemas.card import CardOut, ClaimResultOut
from app.services import claims, customers
from app.services.claims import ClaimResult

router = APIRouter(prefix="/api/c", tags=["c: identity"])

COOKIE_MAX_AGE = CUSTOMER_SESSION_DAYS * 24 * 3600


def claim_result_out(result: ClaimResult) -> dict:
    return {
        "card": result.card,
        "counted": result.counted,
        "new_spins": result.new_spins,
    }


def limit_customer_auth(request: Request, claim_token: str) -> None:
    rate_limit.enforce(
        rate_limit.CUSTOMER_AUTH_PER_IP, "c_auth_ip", rate_limit.client_ip(request)
    )
    rate_limit.enforce(rate_limit.CUSTOMER_AUTH_PER_TOKEN, "c_auth_token", claim_token)


@router.get("/business", response_model=PublicBusinessOut)
async def business(biz: PublicBusiness):
    return {
        "name": biz.name,
        "slug": biz.slug,
        "branding": biz.branding,
        "privacy_policy_version": settings.PRIVACY_POLICY_VERSION,
    }


@router.get("/claims/{token}", response_model=ClaimPreviewOut)
async def claim_preview(token: str, request: Request, db: DbSession):
    rate_limit.enforce(
        rate_limit.CLAIM_PREVIEW_PER_IP, "c_preview_ip", rate_limit.client_ip(request)
    )
    return await claims.claim_preview(db, token)


@router.post("/register", response_model=ClaimResultOut)
async def register(
    body: RegisterIn, request: Request, response: Response, db: DbSession
):
    limit_customer_auth(request, body.claim_token)
    async with db.begin():
        result, token = await claims.register(
            db,
            phone=body.phone,
            alias=body.alias,
            consent=body.consent,
            claim_token=body.claim_token,
            user_agent=request.headers.get("user-agent"),
        )
    set_session_cookie(response, CUSTOMER_COOKIE, token, COOKIE_MAX_AGE)
    return claim_result_out(result)


@router.post("/identify/confirm", response_model=ClaimResultOut)
async def identify_confirm(
    body: IdentifyIn, request: Request, response: Response, db: DbSession
):
    limit_customer_auth(request, body.claim_token)
    async with db.begin():
        result, token = await claims.identify_confirm(
            db,
            phone=body.phone,
            claim_token=body.claim_token,
            user_agent=request.headers.get("user-agent"),
        )
    set_session_cookie(response, CUSTOMER_COOKIE, token, COOKIE_MAX_AGE)
    return claim_result_out(result)


@router.get("/me", response_model=CardOut)
async def me(ctx: CurrentCustomer, db: DbSession):
    return await claims.build_card(db, ctx.customer)


@router.post("/claim", response_model=ClaimResultOut)
async def claim(body: ClaimIn, ctx: CurrentCustomer, db: DbSession):
    async with db.begin():
        result = await claims.claim_with_session(db, ctx.customer, body.claim_token)
    return claim_result_out(result)


@router.get("/history", response_model=list[HistorySale])
async def history(ctx: CurrentCustomer, db: DbSession):
    return await customers.history(db, ctx.customer.id)


@router.post("/logout", status_code=204)
async def logout(ctx: CurrentCustomer, db: DbSession) -> Response:
    async with db.begin():
        session = await db.get(CustomerSession, ctx.session.id)
        session.revoked_at = now_utc()
    response = Response(status_code=204)
    clear_session_cookie(response, CUSTOMER_COOKIE)
    return response
