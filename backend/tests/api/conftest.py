from dataclasses import dataclass, field
from uuid import UUID

import httpx
import pytest

from app.core import rate_limit
from app.main import app
from scripts.create_operator import create_operator
from scripts.seed import seed
from tests.conftest import OWNER_URL

ORIGIN = "http://localhost:5173"
OWNER_EMAIL = "owner@test.local"
OPERATOR_EMAIL = "operator@test.local"
PASSWORD = "correct-horse-battery"

# Section 13: minimal test seed (independent of scripts/seed_data.json).
TEST_DATA = {
    "business": {
        "slug": "test-biz",
        "name": "Test Business",
        "timezone": "America/Bogota",
        "latitude": None,
        "longitude": None,
        "milestone_every": 5,
        "branding": {"display_name": "Test Business"},
    },
    "products": [
        {"sort_order": 1, "name": "Berry Bliss", "price_cop": 14000, "cost_cop": 5000},
        {
            "sort_order": 2,
            "name": "Green Chai Latte",
            "price_cop": 16000,
            "cost_cop": 6000,
        },
        {"sort_order": 3, "name": "Passion Soda", "price_cop": 12000, "cost_cop": 4000},
    ],
    "prize_catalog": [
        {
            "sort_order": 1,
            "name": "10% de descuento",
            "short_label": "10% dto",
            "type": "percent_off",
            "value": 10,
            "max_value_cop": 16000,
            "weight": 40,
            "color": "primary",
            "expires_days": 90,
        },
        {
            "sort_order": 2,
            "name": "Cold foam o topping extra",
            "short_label": "Topping",
            "type": "extra_item",
            "value": 0,
            "max_value_cop": None,
            "weight": 25,
            "color": "secondary",
            "expires_days": 90,
        },
        {
            "sort_order": 3,
            "name": "20% de descuento",
            "short_label": "20% dto",
            "type": "percent_off",
            "value": 20,
            "max_value_cop": 16000,
            "weight": 20,
            "color": "primary",
            "expires_days": 90,
        },
        {
            "sort_order": 4,
            "name": "50% de descuento",
            "short_label": "50% dto",
            "type": "percent_off",
            "value": 50,
            "max_value_cop": 16000,
            "weight": 10,
            "color": "ink",
            "expires_days": 90,
        },
        {
            "sort_order": 5,
            "name": "Bebida gratis",
            "short_label": "Gratis",
            "type": "free_item",
            "value": 0,
            "max_value_cop": 16000,
            "weight": 5,
            "color": "ink",
            "expires_days": 90,
        },
    ],
}


@dataclass
class Seeded:
    business_id: UUID
    products: dict[str, UUID] = field(default_factory=dict)
    prizes: dict[str, UUID] = field(default_factory=dict)
    owner_id: UUID | None = None
    operator_id: UUID | None = None


@pytest.fixture(autouse=True)
def reset_rate_limits():
    rate_limit.reset()


@pytest.fixture
def seeded(owner_conn) -> Seeded:
    seed(OWNER_URL, TEST_DATA)
    business_id = owner_conn.execute(
        "SELECT id FROM business WHERE slug = 'test-biz'"
    ).fetchone()[0]
    s = Seeded(business_id)
    s.products = dict(
        owner_conn.execute(
            "SELECT name, id FROM product WHERE business_id = %s", (business_id,)
        ).fetchall()
    )
    s.prizes = dict(
        owner_conn.execute(
            "SELECT name, id FROM prize_catalog WHERE business_id = %s", (business_id,)
        ).fetchall()
    )
    common = {"business_slug": "test-biz", "password": PASSWORD}
    s.owner_id = create_operator(
        owner_conn, email=OWNER_EMAIL, name="Owner", role="owner", **common
    )
    s.operator_id = create_operator(
        owner_conn, email=OPERATOR_EMAIL, name="Operator", role="operator", **common
    )
    owner_conn.commit()
    return s


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )


@pytest.fixture
async def client(migrated_db):
    """Anonymous client (no cookies)."""
    async with make_client() as c:
        yield c


async def logged_in(email: str) -> httpx.AsyncClient:
    c = make_client()
    r = await c.post("/api/op/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
async def owner(seeded):
    """HTTP client authenticated as the owner."""
    c = await logged_in(OWNER_EMAIL)
    yield c
    await c.aclose()


@pytest.fixture
async def operator(seeded):
    """HTTP client authenticated as a regular operator."""
    c = await logged_in(OPERATOR_EMAIL)
    yield c
    await c.aclose()


@pytest.fixture
async def open_workday(owner) -> dict:
    r = await owner.post("/api/op/workdays/open")
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def weather_api(monkeypatch, owner_conn, seeded):
    """Give the business coordinates and fake Open-Meteo. Returns the request log."""
    import httpx

    from app.services import weather

    owner_conn.execute(
        "UPDATE business SET latitude = 4.723, longitude = -74.042 WHERE id = %s",
        (seeded.business_id,),
    )
    owner_conn.commit()
    calls: list[httpx.Request] = []
    state = {"fail": False}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if state["fail"]:
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(
            200, json={"current": {"temperature_2m": 18.4, "weather_code": 3}}
        )

    monkeypatch.setattr(weather, "TRANSPORT", httpx.MockTransport(handler))
    return {"calls": calls, "state": state}


async def sell(client, items: list[tuple[UUID, int]], *, key=None, **extra):
    """POST /api/op/sales with a fresh Idempotency-Key (unless given)."""
    from uuid import uuid4

    body = {
        "items": [{"product_id": str(p), "qty": q} for p, q in items],
        "payment_method": extra.pop("payment_method", "cash"),
        **{k: (str(v) if v is not None else None) for k, v in extra.items()},
    }
    return await client.post(
        "/api/op/sales", json=body, headers={"Idempotency-Key": str(key or uuid4())}
    )


def make_customer(conn, business_id, phone="+573101234567", alias="Ana") -> UUID:
    customer_id = conn.execute(
        "INSERT INTO customer (business_id, phone, alias, consent_at, consent_version) "
        "VALUES (%s, %s, %s, now(), 'test-v1') RETURNING id",
        (business_id, phone, alias),
    ).fetchone()[0]
    conn.commit()
    return customer_id


class PickPrize:
    """Deterministic RNG (section 13): always draws the prize with this name."""

    def __init__(self, name: str) -> None:
        self.name = name

    def choices(self, population, weights=None, k=1):
        return [next(p for p in population if p.name == self.name)] * k


@pytest.fixture
def rng():
    """rng("Bebida gratis") makes the next spins award that prize."""
    from app.api.deps import get_rng

    def pick(name: str) -> None:
        app.dependency_overrides[get_rng] = lambda: PickPrize(name)

    pick("10% de descuento")
    yield pick
    app.dependency_overrides.pop(get_rng, None)


@pytest.fixture
async def customer_client(migrated_db):
    """A customer's browser (own cookie jar)."""
    async with make_client() as c:
        yield c


def claim_token(conn, sale_id) -> str:
    return conn.execute(
        "SELECT claim_token FROM sale WHERE id = %s", (str(sale_id),)
    ).fetchone()[0]


async def register(c, token, phone="310 123 4567", alias="Ana"):
    return await c.post(
        "/api/c/register",
        json={"phone": phone, "alias": alias, "consent": True, "claim_token": token},
    )


def add_past_purchases(conn, seeded, customer_id, n: int) -> None:
    """n counted purchases in n past, closed workdays (plus the welcome spin)."""
    from datetime import timedelta

    from app.core.time import local_today

    # Business-local date, not the database's UTC current_date.
    today = local_today("America/Bogota")
    first_sale = None
    for days_ago in range(n, 0, -1):
        workday_id = conn.execute(
            "INSERT INTO workday (business_id, local_date, day_type, status, opened_by, "
            "closed_at, closed_by) VALUES (%s, %s, 'other', 'closed', %s, "
            "now(), %s) RETURNING id",
            (
                seeded.business_id,
                today - timedelta(days=days_ago),
                seeded.owner_id,
                seeded.owner_id,
            ),
        ).fetchone()[0]
        sale_id = conn.execute(
            "INSERT INTO sale (business_id, workday_id, operator_id, customer_id, status, "
            "payment_method, total_cop, idempotency_key, claim_token, claim_expires_at, "
            "claim_method, claimed_at, paid_at) VALUES (%s, %s, %s, %s, 'claimed', 'cash', "
            "14000, gen_random_uuid(), gen_random_uuid()::text, now(), 'qr', "
            "now() - make_interval(days => %s), now() - make_interval(days => %s)) "
            "RETURNING id",
            (
                seeded.business_id,
                workday_id,
                seeded.owner_id,
                customer_id,
                days_ago,
                days_ago,
            ),
        ).fetchone()[0]
        first_sale = first_sale or sale_id
    conn.execute(
        "INSERT INTO spin (business_id, customer_id, reason, unlocked_by_sale_id) "
        "VALUES (%s, %s, 'welcome', %s)",
        (seeded.business_id, customer_id, first_sale),
    )
    conn.commit()


async def customer_with_prize(
    owner, seeded, conn, c, rng, prize_name, phone="3101234567"
):
    """Register a customer through a real sale and spin the welcome spin.

    Returns (customer_id, prize_award_id, sale_id of the welcome sale).
    """
    rng(prize_name)
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    body = (await register(c, claim_token(conn, sale["id"]), phone=phone)).json()
    spin_id = body["new_spins"][0]["id"]
    award = (await c.post(f"/api/c/spins/{spin_id}/spin")).json()["prize_award"]
    return body["card"]["customer"]["id"], award["id"], sale["id"]


def prize_status(conn, award_id) -> str:
    return conn.execute(
        "SELECT status FROM prize_award WHERE id = %s", (str(award_id),)
    ).fetchone()[0]
