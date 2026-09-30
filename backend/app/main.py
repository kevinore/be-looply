import sentry_sdk
from fastapi import FastAPI

from app.api import health
from app.api.c import events as c_events
from app.api.c import identity as c_identity
from app.api.c import wheel as c_wheel
from app.api.deps import origin_check_middleware
from app.api.op import auth as op_auth
from app.api.op import customers as op_customers
from app.api.op import events as op_events
from app.api.op import prizes as op_prizes
from app.api.op import products as op_products
from app.api.op import sales as op_sales
from app.api.op import stats as op_stats
from app.api.op import workdays as op_workdays
from app.core.config import settings
from app.core.errors import register_error_handlers

SENTRY_OPTIONS = {
    # Never send request bodies (passwords, phones) or personal data to Sentry.
    "max_request_body_size": "never",
    "send_default_pii": False,
}

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN, environment=settings.APP_ENV, **SENTRY_OPTIONS
    )

is_production = settings.APP_ENV == "production"

app = FastAPI(
    title="Loyalty & Sales API",
    docs_url=None if is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if is_production else "/api/openapi.json",
)

register_error_handlers(app)
# No CORS middleware: the frontend and the API share the same origin.
app.middleware("http")(origin_check_middleware)

app.include_router(health.router)
app.include_router(op_auth.router)
app.include_router(op_workdays.router)
app.include_router(op_products.router)
app.include_router(op_sales.router)
app.include_router(op_customers.router)
app.include_router(op_prizes.router)
app.include_router(op_stats.router)
app.include_router(op_events.router)
app.include_router(c_identity.router)
app.include_router(c_wheel.router)
app.include_router(c_events.router)
