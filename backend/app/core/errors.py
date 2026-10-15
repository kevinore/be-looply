import logging

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

# Section 14.2: code -> (HTTP status, user message)
ERROR_CATALOG: dict[str, tuple[int, str]] = {
    "validation_error": (422, "Revisa los datos ingresados."),
    "invalid_phone": (422, "Ese número no parece un celular colombiano."),
    "consent_required": (
        422,
        "Debes aceptar el tratamiento de datos para continuar.",
    ),
    "product_invalid": (422, "Uno de los productos ya no está disponible."),
    "prize_target_invalid": (422, "Ese premio no aplica a esa bebida."),
    # Not in 14.2: product options (migration 0005).
    "options_invalid": (422, "Revisa las opciones del producto."),
    "invalid_credentials": (401, "Correo o contraseña incorrectos."),
    "not_authenticated": (401, "Tu sesión terminó. Ingresa de nuevo."),
    "forbidden": (403, "No tienes permiso para esta acción."),
    "forbidden_origin": (403, "Solicitud no permitida."),
    "claim_not_found": (404, "No encontramos esa compra."),
    "customer_not_found": (404, "No encontramos ese cliente."),
    "sale_not_found": (404, "No encontramos esa venta."),
    # Not in 14.2: needed by GET /api/op/stats/workdays/{id}.
    "workday_not_found": (404, "No encontramos esa jornada."),
    "spin_not_found": (404, "No encontramos ese giro."),
    "prize_not_found": (404, "No encontramos ese premio."),
    "customer_exists": (409, "Ya existe un cliente con ese celular."),
    "claim_already_claimed": (409, "Esta compra ya fue reclamada."),
    "workday_not_open": (409, "Abre la jornada para vender."),
    "workday_already_open": (409, "Ya hay una jornada abierta."),
    "sale_not_linkable": (409, "Esta venta ya no se puede modificar."),
    "sale_has_prize": (
        409,
        "Esta venta usó un premio: anúlala en lugar de desvincularla.",
    ),
    "sale_already_void": (409, "Esta venta ya estaba anulada."),
    "prize_not_active": (409, "Este premio ya fue usado."),
    "prize_already_in_sale": (409, "Solo se puede usar un premio por compra."),
    "discount_needs_new_sale": (409, "Los descuentos se aplican en una compra nueva."),
    "spin_not_available": (409, "Este giro ya no está disponible."),
    "claim_expired": (410, "Este código venció."),
    "claim_voided": (410, "Esta compra fue anulada."),
    "prize_expired": (410, "Este premio venció."),
    "rate_limited": (429, "Demasiados intentos. Espera un momento."),
    "internal_error": (500, "Algo salió mal. Intenta de nuevo."),
}

# Section 14.3: constraint / index name -> error code
CONSTRAINT_ERRORS: dict[str, str] = {
    "customer_business_id_phone_key": "customer_exists",
    "workday_one_open": "workday_already_open",
    # Two requests opening the first workday of the day at once.
    "workday_business_id_local_date_key": "workday_already_open",
    "prize_one_per_sale": "prize_already_in_sale",
}


class AppError(Exception):
    def __init__(
        self,
        code: str,
        status: int | None = None,
        message: str | None = None,
        extra: dict | None = None,
    ) -> None:
        default_status, default_message = ERROR_CATALOG[code]
        self.code = code
        self.status = status or default_status
        self.message = message or default_message
        self.extra = extra or {}
        super().__init__(code)


def error_response(
    code: str,
    status: int | None = None,
    message: str | None = None,
    extra: dict | None = None,
) -> JSONResponse:
    err = AppError(code, status, message, extra)
    return JSONResponse(
        status_code=err.status,
        content={
            "error": {"code": err.code, "message": err.message, "extra": err.extra}
        },
    )


def constraint_name(exc: IntegrityError) -> str | None:
    """Constraint name from the driver error (asyncpg or psycopg)."""
    orig = exc.orig
    for candidate in (getattr(orig, "__cause__", None), orig):
        name = getattr(candidate, "constraint_name", None)
        if name:
            return name
        diag = getattr(candidate, "diag", None)
        if diag is not None and getattr(diag, "constraint_name", None):
            return diag.constraint_name
    return None


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.code, exc.status, exc.message, exc.extra)


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return error_response("validation_error")


async def integrity_error_handler(
    request: Request, exc: IntegrityError
) -> JSONResponse:
    code = CONSTRAINT_ERRORS.get(constraint_name(exc) or "")
    if code:
        return error_response(code)
    # Never return the raw PostgreSQL message.
    sentry_sdk.capture_exception(exc)
    logger.exception("Unmapped integrity error")
    return error_response("internal_error")


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    sentry_sdk.capture_exception(exc)
    logger.exception("Unhandled error")
    return error_response("internal_error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
