"""11.1 Operator authentication."""

from scripts.reset_operator_password import reset_operator_password
from tests.api.conftest import OPERATOR_EMAIL, OWNER_EMAIL, PASSWORD


async def test_login_sets_cookie_and_returns_body(client, seeded):
    r = await client.post(
        "/api/admin/auth/login",
        json={"email": OWNER_EMAIL.upper(), "password": PASSWORD},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["operator"]["role"] == "owner"
    assert body["business"]["slug"] == "test-biz"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("admin_session=")
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    assert "domain" not in cookie.lower()
    me = await client.get("/api/admin/auth/me")
    assert me.status_code == 200
    assert me.json() == body


async def test_session_token_is_stored_hashed(client, seeded, owner_conn):
    await client.post(
        "/api/admin/auth/login", json={"email": OWNER_EMAIL, "password": PASSWORD}
    )
    token = client.cookies["admin_session"]
    stored = owner_conn.execute("SELECT token_hash FROM operator_session").fetchone()[0]
    assert stored != token
    assert len(stored) == 64


async def test_wrong_password(client, seeded):
    r = await client.post(
        "/api/admin/auth/login", json={"email": OWNER_EMAIL, "password": "nope"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


async def test_unknown_email(client, seeded):
    r = await client.post(
        "/api/admin/auth/login", json={"email": "who@test.local", "password": PASSWORD}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


async def test_inactive_operator_cannot_login(client, seeded, owner_conn):
    owner_conn.execute("UPDATE operator SET active = false")
    owner_conn.commit()
    r = await client.post(
        "/api/admin/auth/login", json={"email": OWNER_EMAIL, "password": PASSWORD}
    )
    assert r.status_code == 401


async def test_login_emits_event(owner, owner_conn):
    count = owner_conn.execute(
        "SELECT count(*) FROM event WHERE type = 'operator_logged_in'"
    ).fetchone()[0]
    assert count == 1


async def test_logout_revokes_session(owner):
    r = await owner.post("/api/admin/auth/logout")
    assert r.status_code == 204
    assert (await owner.get("/api/admin/auth/me")).status_code == 401


async def test_op_without_cookie(client, seeded):
    r = await client.get("/api/admin/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "not_authenticated"


async def test_login_rate_limited_after_5_failures(client, seeded):
    for _ in range(5):
        r = await client.post(
            "/api/admin/auth/login", json={"email": OWNER_EMAIL, "password": "bad"}
        )
        assert r.status_code == 401
    r = await client.post(
        "/api/admin/auth/login", json={"email": OWNER_EMAIL, "password": "bad"}
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"


async def test_reset_password_revokes_sessions(operator, owner_conn):
    revoked = reset_operator_password(
        owner_conn, email=OPERATOR_EMAIL, password="a-brand-new-password"
    )
    owner_conn.commit()
    assert revoked == 1
    assert (await operator.get("/api/admin/auth/me")).status_code == 401
