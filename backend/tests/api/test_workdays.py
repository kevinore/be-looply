"""11.2 Workday, 11.3 Weather, 11.4 Products."""

from app.core.time import day_type, local_today


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


async def test_close_then_open_again_same_day(owner, open_workday):
    r = await owner.post("/api/op/workdays/current/close")
    assert r.status_code == 200
    summary = r.json()
    assert summary["workday_id"] == open_workday["id"]
    assert summary["status"] == "closed"
    assert summary["sales"] == 0
    r = await owner.post("/api/op/workdays/open")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "workday_already_closed_today"


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
    assert set(r.json()[0]) == {"id", "name", "price_cop", "photo_url"}
