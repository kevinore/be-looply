"""11.2 Workday, 11.3 Weather, 11.4 Products."""

from uuid import uuid4

from app.core.time import day_type, local_today
from tests.api.conftest import claim_token, register, sell


async def test_no_current_workday(owner):
    r = await owner.get("/api/op/workdays/current")
    assert r.status_code == 200
    assert r.json() is None


async def test_open_workday_with_weather(owner, weather_api, owner_conn):
    r = await owner.post("/api/op/workdays/open")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "open"
    assert body["local_date"] == local_today("America/Bogota").isoformat()
    assert body["day_type"] == day_type(local_today("America/Bogota"))
    assert body["weather_temp_c"] == 18.4
    assert body["weather_code"] == 3
    params = weather_api["calls"][0].url.params
    assert params["current"] == "temperature_2m,weather_code"
    assert params["timezone"] == "America/Bogota"
    payload = owner_conn.execute(
        "SELECT payload FROM event WHERE type = 'workday_opened'"
    ).fetchone()[0]
    assert payload == {
        "weather_temp_c": 18.4,
        "weather_code": 3,
        "day_type": body["day_type"],
    }
    current = await owner.get("/api/op/workdays/current")
    assert current.json()["id"] == body["id"]


async def test_weather_down_opens_without_weather(owner, weather_api):
    weather_api["state"]["fail"] = True
    r = await owner.post("/api/op/workdays/open")
    assert r.status_code == 201
    assert r.json()["weather_temp_c"] is None
    assert r.json()["weather_code"] is None


async def test_no_coordinates_no_weather_call(owner, monkeypatch):
    import httpx

    from app.services import weather

    def handler(request):
        raise AssertionError("must not call the weather API")

    monkeypatch.setattr(weather, "TRANSPORT", httpx.MockTransport(handler))
    r = await owner.post("/api/op/workdays/open")
    assert r.status_code == 201
    assert r.json()["weather_temp_c"] is None


async def test_open_twice(owner, open_workday):
    r = await owner.post("/api/op/workdays/open")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "workday_already_open"
    assert err["extra"] == {"workday_id": open_workday["id"]}


async def test_close_then_reopen_same_day(owner, open_workday, seeded, owner_conn):
    """Same local date: reopening continues the same workday and keeps its sales."""
    berry = seeded.products["Berry Bliss"]
    assert (await sell(owner, [(berry, 2)])).status_code == 201
    r = await owner.post("/api/op/workdays/current/close")
    assert r.status_code == 200
    summary = r.json()
    assert summary["workday_id"] == open_workday["id"]
    assert summary["status"] == "closed"
    assert summary["sales"] == 1

    r = await owner.post("/api/op/workdays/open")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == open_workday["id"]
    assert body["status"] == "open"
    assert body["closed_at"] is None
    assert body["opened_at"] == open_workday["opened_at"]  # first opening is kept
    assert (await sell(owner, [(berry, 1)])).status_code == 201

    r = await owner.post("/api/op/workdays/current/close")
    assert r.json()["workday_id"] == open_workday["id"]
    assert r.json()["sales"] == 2
    assert r.json()["drinks"] == 3
    count = owner_conn.execute("SELECT count(*) FROM workday").fetchone()[0]
    assert count == 1
    events = [
        t
        for (t,) in owner_conn.execute(
            "SELECT type FROM event WHERE type LIKE 'workday_%' ORDER BY server_ts"
        )
    ]
    assert events == [
        "workday_opened",
        "workday_closed",
        "workday_reopened",
        "workday_closed",
    ]


async def test_reopen_revives_pending_qr(
    owner, open_workday, seeded, owner_conn, customer_client
):
    """R7: closing expires unscanned QR codes; reopening the same day revives them."""
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    token = claim_token(owner_conn, sale["id"])
    await owner.post("/api/op/workdays/current/close")
    preview = (await customer_client.get(f"/api/c/claims/{token}")).json()
    assert preview["state"] == "expired"

    await owner.post("/api/op/workdays/open")
    preview = (await customer_client.get(f"/api/c/claims/{token}")).json()
    assert preview["state"] == "claimable"
    r = await register(customer_client, token)
    assert r.status_code == 200, r.text


async def test_workday_sales_list(owner, open_workday, seeded, owner_conn):
    berry, latte = seeded.products["Berry Bliss"], seeded.products["Green Chai Latte"]
    first = (await sell(owner, [(berry, 2), (latte, 1)])).json()
    second = (await sell(owner, [(latte, 1)], payment_method="transfer")).json()
    await owner.post(f"/api/op/sales/{second['id']}/void", json={"reason": "error"})

    r = await owner.get(f"/api/op/workdays/{open_workday['id']}/sales")
    assert r.status_code == 200, r.text
    page = r.json()
    assert (page["total"], page["voided"], page["next_cursor"]) == (1, 1, None)
    rows = page["items"]
    assert [s["id"] for s in rows] == [second["id"], first["id"]]  # newest first
    assert rows[0]["status"] == "void"
    assert rows[0]["void_reason"] == "error"
    assert rows[1]["total_cop"] == 44000
    assert rows[1]["customer"] is None
    assert [(i["label"], i["qty"], i["is_prize"]) for i in rows[1]["items"]] == [
        ("Berry Bliss", 2, False),
        ("Green Chai Latte", 1, False),
    ]


async def test_workday_sales_pages(owner, open_workday, seeded):
    berry = seeded.products["Berry Bliss"]
    ids = [(await sell(owner, [(berry, 1)])).json()["id"] for _ in range(5)]
    url = f"/api/op/workdays/{open_workday['id']}/sales"

    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = (await owner.get(url, params=params)).json()
        assert page["total"] == (5 if pages == 0 else 6)  # totals are live
        seen += [s["id"] for s in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
        # A sale made while paging never shifts or repeats the next pages.
        if pages == 1:
            await sell(owner, [(berry, 1)])
    assert pages == 3
    assert seen == list(reversed(ids))  # each sale once, newest first


async def test_workday_sales_bad_cursor_or_limit(owner, open_workday):
    url = f"/api/op/workdays/{open_workday['id']}/sales"
    assert (await owner.get(url, params={"cursor": "nope"})).status_code == 422
    assert (await owner.get(url, params={"limit": 0})).status_code == 422
    assert (await owner.get(url, params={"limit": 101})).status_code == 422


async def test_workday_sales_unknown(owner, open_workday):
    r = await owner.get(f"/api/op/workdays/{uuid4()}/sales")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "workday_not_found"


async def test_close_without_open_workday(owner):
    r = await owner.post("/api/op/workdays/current/close")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "workday_not_open"


async def test_close_emits_event_with_summary(owner, open_workday, owner_conn):
    await owner.post("/api/op/workdays/current/close")
    payload = owner_conn.execute(
        "SELECT payload FROM event WHERE type = 'workday_closed'"
    ).fetchone()[0]
    assert payload["workday_id"] == open_workday["id"]
    assert payload["sales"] == 0


async def test_products_sorted_and_active_only(owner, owner_conn, seeded):
    owner_conn.execute("UPDATE product SET active = false WHERE name = 'Passion Soda'")
    owner_conn.commit()
    r = await owner.get("/api/op/products")
    assert r.status_code == 200
    assert [p["name"] for p in r.json()] == ["Berry Bliss", "Green Chai Latte"]
    assert set(r.json()[0]) == {
        "id",
        "name",
        "price_cop",
        "photo_url",
        "description",
        "category",
        "prize_eligible",
        "option_groups",
    }
