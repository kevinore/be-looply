from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentOperator
from app.core import rate_limit
from app.core.db import DbSession
from app.core.security import (
    OPERATOR_COOKIE,
    OPERATOR_SESSION_DAYS,
    clear_session_cookie,
    set_session_cookie,
)
from app.schemas.auth import LoginIn, OperatorMeOut
from app.services import auth_operator
from app.services.auth_operator import OperatorContext

router = APIRouter(prefix="/api/admin/auth", tags=["admin: auth"])


def me_body(ctx: OperatorContext) -> OperatorMeOut:
    return OperatorMeOut.model_validate(
        {"operator": ctx.operator, "business": ctx.business}
    )


@router.post("/login", response_model=OperatorMeOut)
async def login(
    body: LoginIn, request: Request, response: Response, db: DbSession
) -> OperatorMeOut:
    rate_limit.enforce(
        rate_limit.LOGIN_PER_IP, "admin_login_ip", rate_limit.client_ip(request)
    )
    rate_limit.enforce(
        rate_limit.LOGIN_PER_EMAIL, "admin_login_email", body.email.strip().lower()
    )
    async with db.begin():
        ctx, token = await auth_operator.login(
            db, body.email, body.password, request.headers.get("user-agent")
        )
    set_session_cookie(
        response, OPERATOR_COOKIE, token, OPERATOR_SESSION_DAYS * 24 * 3600
    )
    return me_body(ctx)


@router.post("/logout", status_code=204)
async def logout(ctx: CurrentOperator, db: DbSession) -> Response:
    async with db.begin():
        await auth_operator.logout(db, ctx)
    response = Response(status_code=204)
    clear_session_cookie(response, OPERATOR_COOKIE)
    return response


@router.get("/me", response_model=OperatorMeOut)
async def me(ctx: CurrentOperator) -> OperatorMeOut:
    return me_body(ctx)
