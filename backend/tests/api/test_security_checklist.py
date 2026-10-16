"""Phase 7: security checklist, one test (or group) per item."""

import re
import subprocess
import sys
from uuid import uuid4

import httpx
import pytest
from starlette.responses import Response

from app.main import app
from scripts.check_grants import check_grants
from scripts.create_operator import create_operator
from scripts.seed import seed
from tests.api.conftest import (
    ORIGIN,
    PASSWORD,
    TEST_DATA,
    claim_token,
    customer_with_prize,
    logged_in,
    make_client,
    make_customer,
    register,
    sell,
)
from tests.conftest import BACKEND_DIR, OWNER_URL, RUNTIME_URL


# --- Passwords: argon2, never logged -------------------------------------------------
def test_sentry_never_receives_bodies_or_pii():
    from app.main import SENTRY_OPTIONS

    assert SENTRY_OPTIONS == {
        "max_request_body_size": "never",
        "send_default_pii": False,
    }


async def test_password_stored_as_argon2(seeded, owner_conn):
    hashes = [h for (h,) in owner_conn.execute("SELECT password_hash FROM operator")]
    assert hashes and all(h.startswith("$argon2id$") for h in hashes)
    assert all(PASSWORD not in h for h in hashes)


# --- Cookies: HttpOnly, Secure in production, SameSite=Lax, no domain -----------------
@pytest.mark.parametrize("secure", [False, True])
def test_session_cookie_flags(monkeypatch, secure):
    from app.core import security

    monkeypatch.setattr(security.settings, "COOKIE_SECURE", secure)
    response = Response()
    security.set_session_cookie(response, "client_session", "tok", 60)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "domain" not in cookie
    assert ("secure" in cookie) is secure


# --- Every /api/admin/* requires get_current_operator, except login ---------------------
def admin_routes():
    # From the OpenAPI schema: this FastAPI version groups app.routes by router.
    for path, operations in app.openapi()["paths"].items():
        if path.startswith("/api/admin/") and path != "/api/admin/auth/login":
            for method in operations:
                yield method.upper(), path


def test_op_routes_are_collected():
    assert (
        len(list(admin_routes())) == 23
    )  # 14.1: 23 operator routes minus login, + wheel editor


@pytest.mark.parametrize(("method", "path"), sorted(admin_routes()))
async def test_op_route_requires_operator(client, seeded, method, path):
    url = re.sub(r"\{[^}]+\}", str(uuid4()), path)
    r = await client.request(method, url, json={} if method == "POST" else None)
    assert r.status_code == 401, (method, path, r.text)
    assert r.json()["error"]["code"] == "not_authenticated"


# --- R21: everything filtered by the authenticated user's business --------------------
@pytest.fixture
async def other_business_operator(seeded, owner_conn):
    data = {
        **TEST_DATA,
        "business": {**TEST_DATA["business"], "slug": "other-biz", "name": "Other"},
    }
    seed(OWNER_URL, data)
    create_operator(
        owner_conn,
        business_slug="other-biz",
        email="other@test.local",
        name="Other",
        role="owner",
        password=PASSWORD,
    )
    owner_conn.commit()
    c = await logged_in("other@test.local")
    yield c
    await c.aclose()


async def test_business_isolation(
    owner, open_workday, seeded, owner_conn, other_business_operator, rng
):
    other = other_business_operator
    berry = seeded.products["Berry Bliss"]
    async with make_client() as ana:
        customer_id, award_id, sale_id = await customer_with_prize(
            owner, seeded, owner_conn, ana, rng, "Cold foam o topping extra"
        )
    anonymous = (await sell(owner, [(berry, 1)])).json()["id"]
    await other.post("/api/admin/workdays/open")

    def code(r):
        return r.json()["error"]["code"]

    assert code(await other.get(f"/api/admin/sales/{sale_id}")) == "sale_not_found"
    assert (
        code(await other.get(f"/api/admin/sales/{sale_id}/status")) == "sale_not_found"
    )
    assert (
        code(
            await other.post(
                f"/api/admin/sales/{anonymous}/link", json={"customer_id": customer_id}
            )
        )
        == "sale_not_linkable"
    )
    assert (
        code(await other.post(f"/api/admin/sales/{sale_id}/unlink"))
        == "sale_not_linkable"
    )
    assert (
        code(
            await other.post(
                f"/api/admin/sales/{sale_id}/void", json={"reason": "x" * 5}
            )
        )
        == "sale_not_found"
    )
    assert (
        code(
            await other.post(
                f"/api/admin/sales/{sale_id}/redeem-prize",
                json={"prize_award_id": award_id},
            )
        )
        == "sale_not_linkable"
    )
    assert (await other.get("/api/admin/customers/search?last4=4567")).json() == []
    assert (
        code(await other.get(f"/api/admin/customers/{customer_id}"))
        == "customer_not_found"
    )
    assert (
        code(await other.get(f"/api/admin/stats/workdays/{open_workday['id']}"))
        == "workday_not_found"
    )
    assert (await other.get("/api/admin/prizes/pending")).json() == []
    assert code(await sell(other, [(berry, 1)])) == "product_invalid"
    other_product = owner_conn.execute(
        "SELECT p.id FROM product p JOIN business b ON b.id = p.business_id "
        "WHERE b.slug = 'other-biz' LIMIT 1"
    ).fetchone()[0]
    assert (
        code(await sell(other, [(other_product, 1)], customer_id=customer_id))
        == "customer_not_found"
    )
    # Products listed are only the operator's own.
    names_ids = {p["id"] for p in (await other.get("/api/admin/products")).json()}
    assert str(berry) not in names_ids


async def test_customer_cannot_claim_other_business_sale(
    seeded, owner_conn, other_business_operator, owner, open_workday
):
    other = other_business_operator
    await other.post("/api/admin/workdays/open")
    other_product = owner_conn.execute(
        "SELECT p.id FROM product p JOIN business b ON b.id = p.business_id "
        "WHERE b.slug = 'other-biz' LIMIT 1"
    ).fetchone()[0]
    foreign = (await sell(other, [(other_product, 1)])).json()
    mine = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    async with make_client() as c:
        await register(c, claim_token(owner_conn, mine["id"]))
        r = await c.post(
            "/api/client/claim",
            json={"claim_token": claim_token(owner_conn, foreign["id"])},
        )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "claim_not_found"


# --- Customer responses only with phone_last4 -----------------------------------------
async def test_customer_responses_never_show_full_phone(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    token = claim_token(owner_conn, sale["id"])
    responses = [await customer_client.get(f"/api/client/claims/{token}")]
    responses.append(await register(customer_client, token))
    spin_id = responses[-1].json()["new_spins"][0]["id"]
    responses.append(await customer_client.post(f"/api/client/spins/{spin_id}/spin"))
    award_id = responses[-1].json()["prize_award"]["id"]
    for path in (
        "/api/client/me",
        "/api/client/history",
        f"/api/client/prizes/{award_id}",
    ):
        responses.append(await customer_client.get(path))
    # The operator side also only shows the last 4 digits.
    responses.append(await owner.get(f"/api/admin/sales/{sale['id']}/status"))
    responses.append(await owner.get("/api/admin/customers/search?last4=4567"))
    responses.append(await owner.get("/api/admin/prizes/pending"))
    for r in responses:
        assert r.status_code == 200, r.text
        assert "3101234567" not in r.text
        assert "+57" not in r.text


# --- Prize weights never in customer endpoints ----------------------------------------
async def test_weights_never_in_customer_endpoints(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    body = (await register(customer_client, claim_token(owner_conn, sale["id"]))).json()
    spin = await customer_client.post(
        f"/api/client/spins/{body['new_spins'][0]['id']}/spin"
    )
    for r in (
        spin,
        await customer_client.get("/api/client/wheel"),
        await customer_client.get("/api/client/me"),
    ):
        assert "weight" not in r.text


# --- Errors without internal details --------------------------------------------------
async def test_unhandled_error_hides_details(monkeypatch, seeded):
    from app.services import prizes

    async def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail: postgres://owner:pw@host")

    monkeypatch.setattr(prizes, "active_catalog", boom)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/client/wheel")
    assert r.status_code == 500
    assert r.json() == {
        "error": {
            "code": "internal_error",
            "message": "Algo salió mal. Intenta de nuevo.",
            "extra": {},
        }
    }
    assert "secret" not in r.text


async def test_unmapped_integrity_error_hides_postgres_message(
    owner, open_workday, seeded, owner_conn
):
    # Force a CHECK violation the API does not map (negative price in the database).
    owner_conn.execute(
        "ALTER TABLE sale_item DROP CONSTRAINT sale_item_unit_price_cop_check"
    )
    owner_conn.execute("UPDATE product SET price_cop = 1")
    owner_conn.execute(
        "ALTER TABLE sale_item ADD CONSTRAINT sale_item_unit_price_cop_check "
        "CHECK (unit_price_cop >= 2) NOT VALID"
    )
    owner_conn.commit()
    try:
        r = await sell(owner, [(seeded.products["Berry Bliss"], 1)])
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "internal_error"
        assert "violates" not in r.text
        assert "sale_item" not in r.text
    finally:
        owner_conn.execute(
            "ALTER TABLE sale_item DROP CONSTRAINT sale_item_unit_price_cop_check"
        )
        owner_conn.execute(
            "ALTER TABLE sale_item ADD CONSTRAINT sale_item_unit_price_cop_check "
            "CHECK (unit_price_cop >= 0)"
        )
        owner_conn.commit()


# --- app_runtime without DELETE and without UPDATE on event (check_grants.py) ---------
def test_check_grants_passes(migrated_db):
    assert all(ok for _, ok in check_grants(RUNTIME_URL))


def test_check_grants_detects_a_leaked_privilege(owner_conn):
    owner_conn.execute("GRANT DELETE ON product TO app_runtime")
    owner_conn.commit()
    try:
        results = dict(check_grants(RUNTIME_URL))
        assert results["DELETE product"] is False
        assert results["DELETE sale"] is True
    finally:
        owner_conn.execute("REVOKE DELETE ON product FROM app_runtime")
        owner_conn.commit()


def test_check_grants_detects_inherited_privileges(owner_conn):
    """Reproduces Neon: Console roles inherit pg_write_all_data via neon_superuser."""
    owner_conn.execute("GRANT pg_write_all_data TO app_runtime")
    owner_conn.commit()
    try:
        results = dict(check_grants(RUNTIME_URL))
        assert results["DELETE sale"] is False
        assert results["UPDATE event"] is False
        assert results["no inherited roles ['pg_write_all_data']"] is False
    finally:
        owner_conn.execute("REVOKE pg_write_all_data FROM app_runtime")
        owner_conn.commit()


def test_check_grants_detects_role_attributes(owner_conn):
    owner_conn.execute("ALTER ROLE app_runtime CREATEROLE")
    owner_conn.commit()
    try:
        results = dict(check_grants(RUNTIME_URL))
        assert results["no SUPERUSER/CREATEROLE/CREATEDB/BYPASSRLS"] is False
    finally:
        owner_conn.execute("ALTER ROLE app_runtime NOCREATEROLE")
        owner_conn.commit()


# --- /api/docs disabled in production; OpenAPI still exportable -----------------------
def test_docs_disabled_in_production():
    code = (
        "from app.main import app;"
        "print(app.docs_url, app.redoc_url, app.openapi_url, len(app.openapi()['paths']))"
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "APP_ENV": "production",
        "DATABASE_URL": RUNTIME_URL,
        "DEFAULT_BUSINESS_SLUG": "x",
        "PRIVACY_POLICY_VERSION": "x",
        "COOKIE_SECURE": "true",
    }
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    docs, redoc, openapi, paths = out.stdout.split()
    assert (docs, redoc, openapi) == ("None", "None", "None")
    assert int(paths) == 36


async def test_docs_enabled_outside_production(client):
    assert (await client.get("/api/docs")).status_code == 200


# --- Rate limits configured -----------------------------------------------------------
async def test_login_rate_limit_per_ip(client, seeded):
    for i in range(20):
        await client.post(
            "/api/admin/auth/login", json={"email": f"u{i}@test.local", "password": "x"}
        )
    r = await client.post(
        "/api/admin/auth/login", json={"email": "u99@test.local", "password": "x"}
    )
    assert r.status_code == 429


async def test_rate_limit_uses_first_forwarded_ip(seeded):
    async with make_client() as c:
        for _ in range(20):
            await c.post(
                "/api/admin/auth/login",
                json={"email": "a@test.local", "password": "x"},
                headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"},
            )
        # Another client IP (first value) is not affected.
        r = await c.post(
            "/api/admin/auth/login",
            json={"email": "b@test.local", "password": "x"},
            headers={"X-Forwarded-For": "2.2.2.2, 10.0.0.1"},
        )
        assert r.status_code == 401


async def test_identify_rate_limit_per_ip(customer_client, seeded):
    for i in range(10):
        await customer_client.post(
            "/api/client/identify/confirm",
            json={"phone": "3101234567", "claim_token": f"t{i}"},
        )
    r = await customer_client.post(
        "/api/client/identify/confirm",
        json={"phone": "3101234567", "claim_token": "t99"},
    )
    assert r.status_code == 429


async def test_claim_preview_rate_limit(customer_client, seeded):
    for i in range(30):
        await customer_client.get(f"/api/client/claims/t{i}")
    assert (await customer_client.get("/api/client/claims/t99")).status_code == 429


# --- Prices never accepted from the frontend (also in test_sales) ---------------------
def test_sale_input_schema_has_no_prices():
    from app.schemas.sale import SaleCreateIn, SaleItemIn

    fields = set(SaleCreateIn.model_fields) | set(SaleItemIn.model_fields)
    assert not any("price" in f or "total" in f or "discount" in f for f in fields)


# --- Registration and identification require a valid claim_token (R5) ---------------
async def test_no_customer_lookup_without_token(customer_client, seeded, owner_conn):
    make_customer(owner_conn, seeded.business_id)
    r = await customer_client.post(
        "/api/client/identify/confirm",
        json={"phone": "3101234567", "claim_token": "bogus"},
    )
    # Does not reveal that the customer exists.
    assert r.json()["error"]["code"] == "claim_not_found"
    assert "Ana" not in r.text


def test_origin_constant_matches_settings():
    from app.core.config import settings

    assert settings.ALLOWED_ORIGINS == [ORIGIN]


# --- Origin check: JSON Content-Type only required when there is a body -------------
def swagger_like_client(origin: str = ORIGIN) -> httpx.AsyncClient:
    """Like Swagger: sends Origin, and no Content-Type when there is no body."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Origin": origin},
    )


async def test_bodyless_post_without_content_type_is_allowed(seeded):
    async with swagger_like_client() as c:
        r = await c.post(
            "/api/admin/auth/login",
            json={"email": "owner@test.local", "password": PASSWORD},
        )
        assert r.status_code == 200
        r = await c.post("/api/admin/workdays/open")  # no body, no Content-Type
        assert r.status_code == 201, r.text
        r = await c.post("/api/admin/auth/logout")
        assert r.status_code == 204
        assert (await c.get("/api/admin/auth/me")).status_code == 401


async def test_bodyless_post_from_foreign_origin_is_blocked(seeded):
    async with swagger_like_client("https://evil.example") as c:
        r = await c.post("/api/admin/auth/logout")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_origin"


@pytest.mark.parametrize(
    "content_type", [None, "text/plain", "application/x-www-form-urlencoded"]
)
async def test_post_with_body_requires_json(seeded, content_type):
    headers = {"Content-Type": content_type} if content_type else {}
    async with swagger_like_client() as c:
        r = await c.post(
            "/api/admin/auth/login",
            content=b'{"email": "owner@test.local", "password": "x"}',
            headers=headers,
        )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_origin"
