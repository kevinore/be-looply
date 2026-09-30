"""11.5 Create sale, 11.6 other sale endpoints (F4), 13.3 edge cases."""

from uuid import uuid4

from tests.api.conftest import make_customer, sell


async def test_create_sale(owner, open_workday, seeded, owner_conn):
    berry = seeded.products["Berry Bliss"]
    r = await sell(owner, [(berry, 2)])
    assert r.status_code == 201, r.text
    sale = r.json()
    assert sale["status"] == "paid"
    assert sale["total_cop"] == 28000
    assert sale["payment_method"] == "cash"
    assert sale["customer"] is None
    assert sale["items"][0] == {
        "product_id": str(berry),
        "label": "Berry Bliss",
        "qty": 2,
        "unit_price_cop": 14000,
        "discount_cop": 0,
        "prize_award_id": None,
    }
    token = owner_conn.execute(
        "SELECT claim_token FROM sale WHERE id = %s", (sale["id"],)
    ).fetchone()[0]
    assert sale["claim_url"] == f"http://localhost:5173/c/claim/{token}"
    # R3: price and cost copied into sale_item.
    assert owner_conn.execute(
        "SELECT unit_price_cop, unit_cost_cop FROM sale_item"
    ).fetchone() == (14000, 5000)
    payload = owner_conn.execute(
        "SELECT payload FROM event WHERE type = 'sale_paid'"
    ).fetchone()[0]
    assert payload == {
        "total_cop": 28000,
        "payment_method": "cash",
        "items": [{"product_id": str(berry), "qty": 2}],
    }


async def test_same_idempotency_key_creates_one_sale(
    owner, open_workday, seeded, owner_conn
):
    key = uuid4()
    berry = seeded.products["Berry Bliss"]
    first = await sell(owner, [(berry, 1)], key=key)
    second = await sell(owner, [(berry, 1)], key=key)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert owner_conn.execute("SELECT count(*) FROM sale").fetchone()[0] == 1


async def test_concurrent_same_idempotency_key(owner, open_workday, seeded, owner_conn):
    import asyncio

    key = uuid4()
    berry = seeded.products["Berry Bliss"]
    a, b = await asyncio.gather(
        sell(owner, [(berry, 1)], key=key), sell(owner, [(berry, 1)], key=key)
    )
    assert {a.status_code, b.status_code} <= {200, 201}
    assert a.json()["id"] == b.json()["id"]
    assert owner_conn.execute("SELECT count(*) FROM sale").fetchone()[0] == 1


async def test_missing_or_invalid_idempotency_key(owner, open_workday, seeded):
    body = {
        "items": [{"product_id": str(seeded.products["Berry Bliss"]), "qty": 1}],
        "payment_method": "cash",
    }
    r = await owner.post("/api/op/sales", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    r = await owner.post(
        "/api/op/sales", json=body, headers={"Idempotency-Key": "not-a-uuid"}
    )
    assert r.json()["error"]["code"] == "validation_error"


async def test_price_in_body_is_ignored(owner, open_workday, seeded):
    body = {
        "items": [
            {
                "product_id": str(seeded.products["Berry Bliss"]),
                "qty": 1,
                "unit_price_cop": 1,
            }
        ],
        "payment_method": "cash",
        "total_cop": 1,
    }
    r = await owner.post(
        "/api/op/sales", json=body, headers={"Idempotency-Key": str(uuid4())}
    )
    assert r.status_code == 201
    assert r.json()["total_cop"] == 14000


async def test_sale_needs_open_workday(owner, seeded):
    r = await sell(owner, [(seeded.products["Berry Bliss"], 1)])
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "workday_not_open"


async def test_inactive_or_unknown_product(owner, open_workday, seeded, owner_conn):
    owner_conn.execute("UPDATE product SET active = false WHERE name = 'Passion Soda'")
    owner_conn.commit()
    r = await sell(owner, [(seeded.products["Passion Soda"], 1)])
    assert r.json()["error"]["code"] == "product_invalid"
    r = await sell(owner, [(uuid4(), 1)])
    assert r.json()["error"]["code"] == "product_invalid"


async def test_input_validation(owner, open_workday, seeded):
    berry = seeded.products["Berry Bliss"]
    for items in ([], [(berry, 0)], [(berry, 21)], [(berry, 1), (berry, 1)]):
        r = await sell(owner, items)
        assert r.json()["error"]["code"] == "validation_error", items
    r = await sell(owner, [(berry, 1)], payment_method="bitcoin")
    assert r.json()["error"]["code"] == "validation_error"
    r = await sell(owner, [(berry, 1)], prize_award_id=uuid4())
    assert r.json()["error"]["code"] == "validation_error"


async def test_payment_methods_and_totals(owner, open_workday, seeded):
    items = [
        (seeded.products["Berry Bliss"], 1),
        (seeded.products["Green Chai Latte"], 2),
    ]
    r = await sell(owner, items, payment_method="nequi")
    assert r.json()["total_cop"] == 14000 + 2 * 16000
    assert r.json()["payment_method"] == "nequi"


async def test_get_sale_and_status(owner, open_workday, seeded):
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    r = await owner.get(f"/api/op/sales/{sale['id']}")
    assert r.json()["id"] == sale["id"]
    r = await owner.get(f"/api/op/sales/{sale['id']}/status")
    assert r.json() == {"status": "paid", "customer": None}
    r = await owner.get(f"/api/op/sales/{uuid4()}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "sale_not_found"


async def test_f4_manual_link(owner, open_workday, seeded, owner_conn):
    """F4: anonymous sale -> search by last 4 -> manual link."""
    customer_id = make_customer(owner_conn, seeded.business_id)
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()

    found = (await owner.get("/api/op/customers/search?last4=4567")).json()
    assert found == [
        {
            "id": str(customer_id),
            "alias": "Ana",
            "phone_last4": "4567",
            "purchases": 0,
            "active_prizes_count": 0,
        }
    ]
    r = await owner.post(
        f"/api/op/sales/{sale['id']}/link", json={"customer_id": str(customer_id)}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counted"] is True
    assert [s["reason"] for s in body["new_spins"]] == ["welcome"]
    assert body["card"]["purchases"] == 1
    method = owner_conn.execute(
        "SELECT claim_method, status FROM sale WHERE id = %s", (sale["id"],)
    ).fetchone()
    assert method == ("manual", "claimed")
    types = {t for (t,) in owner_conn.execute("SELECT type FROM event").fetchall()}
    assert {"sale_claimed", "sale_linked_manual", "spin_unlocked"} <= types

    status = (await owner.get(f"/api/op/sales/{sale['id']}/status")).json()
    assert status["status"] == "claimed"
    assert status["customer"]["alias"] == "Ana"
    assert status["customer"]["purchases"] == 1

    again = await owner.post(
        f"/api/op/sales/{sale['id']}/link", json={"customer_id": str(customer_id)}
    )
    assert again.json()["error"]["code"] == "sale_not_linkable"


async def test_create_sale_with_customer_links_manual(
    owner, open_workday, seeded, owner_conn
):
    customer_id = make_customer(owner_conn, seeded.business_id)
    r = await sell(
        owner, [(seeded.products["Berry Bliss"], 1)], customer_id=customer_id
    )
    assert r.status_code == 201
    assert r.json()["status"] == "claimed"
    assert r.json()["claim_method"] == "manual"
    assert r.json()["customer"]["phone_last4"] == "4567"


async def test_create_sale_with_unknown_customer(owner, open_workday, seeded):
    r = await sell(owner, [(seeded.products["Berry Bliss"], 1)], customer_id=uuid4())
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "customer_not_found"


async def test_search_requires_4_digits(owner, seeded):
    for value in ("123", "12345", "abcd"):
        r = await owner.get(f"/api/op/customers/search?last4={value}")
        assert r.json()["error"]["code"] == "validation_error"


async def test_customer_detail(owner, open_workday, seeded, owner_conn):
    customer_id = make_customer(owner_conn, seeded.business_id)
    await sell(owner, [(seeded.products["Berry Bliss"], 1)], customer_id=customer_id)
    r = await owner.get(f"/api/op/customers/{customer_id}")
    body = r.json()
    assert body["alias"] == "Ana"
    assert body["phone_last4"] == "4567"
    assert body["purchases"] == 1
    assert body["milestone_every"] == 5
    assert len(body["sales"]) == 1
    assert "phone" not in body
