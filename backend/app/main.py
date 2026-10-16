import sentry_sdk
from fastapi import FastAPI

from app.api import health
from app.api.admin import auth as admin_auth
from app.api.admin import customers as admin_customers
from app.api.admin import events as admin_events
from app.api.admin import prizes as admin_prizes
from app.api.admin import products as admin_products
from app.api.admin import sales as admin_sales
from app.api.admin import stats as admin_stats
from app.api.admin import workdays as admin_workdays
from app.api.client import events as client_events
from app.api.client import identity as client_identity
from app.api.client import wheel as client_wheel
from app.api.deps import origin_check_middleware
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
app.include_router(admin_auth.router)
app.include_router(admin_workdays.router)
app.include_router(admin_products.router)
app.include_router(admin_sales.router)
app.include_router(admin_customers.router)
app.include_router(admin_prizes.router)
app.include_router(admin_stats.router)
app.include_router(admin_events.router)
app.include_router(client_identity.router)
app.include_router(client_wheel.router)
app.include_router(client_events.router)
