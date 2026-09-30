import sentry_sdk
from fastapi import FastAPI

from app.api import health
from app.api.deps import origin_check_middleware
from app.api.op import auth as op_auth
from app.api.op import products as op_products
from app.api.op import workdays as op_workdays
from app.core.config import settings
from app.core.errors import register_error_handlers

if settings.SENTRY_DSN:
    sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.APP_ENV)

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
