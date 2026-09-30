"""11.12 Stats, 11.13 Events, F7 workday flow, 13.3 origin check."""

import csv
import io
from uuid import uuid4

from app.core.time import local_today
from tests.api.conftest import claim_token, make_client, register, sell


async def day_of_sales(owner, seeded, owner_conn):
    """2 Berry (cash), 1 Latte (nequi, claimed), 1 voided Berry."""
    berry, latte = seeded.products["Berry Bliss"], seeded.products["Green Chai Latte"]
    await sell(owner, [(berry, 2)])
    claimed = (await sell(owner, [(latte, 1)], payment_method="nequi")).json()
    async with make_client() as c:
        await register(c, claim_token(owner_conn, claimed["id"]))
    voided = (await sell(owner, [(berry, 5)])).json()
    await owner.post(f"/api/op/sales/{voided['id']}/void", json={"reason": "error"})


async def test_f7_workday(owner, weather_api, seeded, owner_conn, customer_client):
    """F7: open (fake weather) -> sell -> close -> pending QR expired -> summary."""
    workday = (await owner.post("/api/op/workdays/open")).json()
    assert workday["weather_temp_c"] == 18.4
    await day_of_sales(owner, seeded, owner_conn)
    pending = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    token = claim_token(owner_conn, pending["id"])
    assert (await customer_client.get(f"/api/c/claims/{token}")).json()[
        "state"
    ] == "claimable"

    summary = (await owner.post("/api/op/workdays/current/close")).json()
    assert summary == {
        **summary,
        "workday_id": workday["id"],
        "status": "closed",
        "sales": 3,
        "claimed_sales": 1,
        "revenue_cop": 28000 + 16000 + 14000,
        "cash_cop": 28000 + 14000,
        "digital_cop": 16000,
        "drinks": 4,
        "weather_temp_c": 18.4,
    }
    assert (await customer_client.get(f"/api/c/claims/{token}")).json()[
        "state"
    ] == "expired"
    r = await register(customer_client, token)
    assert r.json()["error"]["code"] == "claim_expired"
    # After closing, selling needs an open workday.
    r = await sell(owner, [(seeded.products["Berry Bliss"], 1)])
    assert r.json()["error"]["code"] == "workday_not_open"


async def test_workday_stats(owner, open_workday, seeded, owner_conn):
    await day_of_sales(owner, seeded, owner_conn)
    r = await owner.get(f"/api/op/stats/workdays/{open_workday['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["sales"] == 2
    assert body["summary"]["drinks"] == 3
    assert body["summary"]["drinks_per_sale"] == 1.5
    assert body["summary"]["claimed_pct"] == 0.5
    assert [p["label"] for p in body["top_products"]] == [
        "Berry Bliss",
        "Green Chai Latte",
    ]
    berry = body["top_products"][0]
    assert (berry["units"], berry["net_cop"], berry["margin_cop"]) == (2, 28000, 18000)
    assert body["cost_incomplete"] is False
    assert body["margin_cop"] == (28000 - 10000) + (16000 - 6000)
    assert len(body["hourly"]) == 1
    assert body["hourly"][0]["sales"] == 2
    assert body["best_hour"] == body["hourly"][0]["local_hour"]


async def test_stats_without_cost_hide_margin(owner, open_workday, seeded, owner_conn):
    owner_conn.execute("UPDATE product SET cost_cop = NULL WHERE name = 'Berry Bliss'")
    owner_conn.commit()
    await sell(owner, [(seeded.products["Berry Bliss"], 1)])
    body = (await owner.get(f"/api/op/stats/workdays/{open_workday['id']}")).json()
    assert body["cost_incomplete"] is True
    assert body["margin_cop"] is None
    assert body["top_products"][0]["margin_cop"] is None


async def test_workday_stats_empty_and_unknown(owner, open_workday):
    body = (await owner.get(f"/api/op/stats/workdays/{open_workday['id']}")).json()
    assert body["summary"]["drinks_per_sale"] == 0
    assert body["summary"]["claimed_pct"] == 0
    assert body["best_hour"] is None
    r = await owner.get(f"/api/op/stats/workdays/{uuid4()}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "workday_not_found"


async def test_history_stats(owner, open_workday, seeded, owner_conn):
    await day_of_sales(owner, seeded, owner_conn)
    today = local_today("America/Bogota").isoformat()
    body = (await owner.get(f"/api/op/stats/history?from={today}&to={today}")).json()
    assert [w["workday_id"] for w in body["workdays"]] == [open_workday["id"]]
    assert body["products"][0]["label"] == "Berry Bliss"
    assert body["hourly_average"][0]["avg_sales"] == 2
    r = await owner.get("/api/op/stats/history?from=2026-10-10&to=2026-10-01")
    assert r.json()["error"]["code"] == "validation_error"


async def test_export_csv(owner, operator, open_workday, seeded, owner_conn):
    await day_of_sales(owner, seeded, owner_conn)
    today = local_today("America/Bogota").isoformat()
    r = await owner.get(f"/api/op/export/sales.csv?from={today}&to={today}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 3  # one per sale line, void sale included
    assert sorted(row["status"] for row in rows) == ["claimed", "paid", "void"]
    assert "phone" not in r.text
    r = await operator.get(f"/api/op/export/sales.csv?from={today}&to={today}")
    assert r.status_code == 403


async def test_customer_events(customer_client, seeded, owner_conn):
    r = await customer_client.post(
        "/api/c/events",
        json={"type": "page_loaded", "payload": {"load_ms": 1400}, "client_ts": None},
    )
    assert r.status_code == 204
    row = owner_conn.execute("SELECT actor, actor_id, payload FROM event").fetchone()
    assert row == ("customer", None, {"load_ms": 1400})

    r = await customer_client.post("/api/c/events", json={"type": "sale_qr_shown"})
    assert r.json()["error"]["code"] == "validation_error"
    r = await customer_client.post("/api/c/events", json={"type": "sale_claimed"})
    assert r.json()["error"]["code"] == "validation_error"
    r = await customer_client.post(
        "/api/c/events", json={"type": "page_loaded", "payload": {"x": "a" * 2100}}
    )
    assert r.json()["error"]["code"] == "validation_error"


async def test_operator_events(owner, owner_conn, seeded):
    r = await owner.post("/api/op/events", json={"type": "sale_qr_shown"})
    assert r.status_code == 204
    actor = owner_conn.execute(
        "SELECT actor, actor_id FROM event WHERE type = 'sale_qr_shown'"
    ).fetchone()
    assert actor == ("operator", seeded.owner_id)
    r = await owner.post("/api/op/events", json={"type": "page_loaded"})
    assert r.json()["error"]["code"] == "validation_error"


async def test_events_rate_limit(customer_client, seeded):
    for _ in range(60):
        await customer_client.post("/api/c/events", json={"type": "page_loaded"})
    r = await customer_client.post("/api/c/events", json={"type": "page_loaded"})
    assert r.status_code == 429


async def test_post_with_foreign_origin(owner, seeded):
    """13.3: POST with a foreign Origin -> 403."""
    r = await owner.post(
        "/api/op/workdays/open", headers={"Origin": "https://evil.example"}
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_origin"
    r = await owner.post(
        "/api/op/workdays/open", headers={"Content-Type": "text/plain"}, content="x"
    )
    assert r.status_code == 403
