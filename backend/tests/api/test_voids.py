"""11.8 Void cascade, 11.6 unlink, 13.3 edge cases."""

from tests.api.conftest import (
    add_past_purchases,
    claim_token,
    customer_with_prize,
    make_customer,
    prize_status,
    register,
    sell,
)


def spins(conn):
    return conn.execute(
        "SELECT reason, milestone_n, status, unlocked_by_sale_id::text FROM spin "
        "ORDER BY created_at"
    ).fetchall()


def events(conn, type_):
    return conn.execute(
        "SELECT count(*) FROM event WHERE type = %s", (type_,)
    ).fetchone()[0]


async def void(client, sale_id, reason="Cobro equivocado"):
    return await client.post(f"/api/op/sales/{sale_id}/void", json={"reason": reason})


async def test_void_anonymous_sale(owner, open_workday, seeded, owner_conn):
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    r = await void(owner, sale["id"])
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "void"
    assert body["void_reason"] == "Cobro equivocado"
    payload = owner_conn.execute(
        "SELECT payload FROM event WHERE type = 'sale_voided'"
    ).fetchone()[0]
    assert payload == {"reason": "Cobro equivocado", "previous_status": "paid"}
    r = await void(owner, sale["id"])
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "sale_already_void"


async def test_void_reason_length(owner, open_workday, seeded):
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    for reason in ("ab", "x" * 201):
        r = await void(owner, sale["id"], reason)
        assert r.json()["error"]["code"] == "validation_error"


async def test_void_welcome_available(
    owner, open_workday, seeded, owner_conn, customer_client
):
    """13.3: void the sale that unlocked an available welcome spin -> spin void."""
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    await register(customer_client, claim_token(owner_conn, sale["id"]))
    r = await void(owner, sale["id"])
    assert r.json()["customer"]["alias"] == "Ana"  # customer_id kept as history
    assert [s[2] for s in spins(owner_conn)] == ["void"]
    card = (await customer_client.get("/api/c/me")).json()
    assert card["purchases"] == 0
    assert card["available_spins"] == []


async def test_void_sale_with_active_won_prize(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    """13.3: void the sale whose prize was won and is active -> prize void, spin void."""
    _, award_id, sale_id = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "10% de descuento"
    )
    await void(owner, sale_id)
    assert prize_status(owner_conn, award_id) == "void"
    assert [s[2] for s in spins(owner_conn)] == ["void"]
    assert events(owner_conn, "prize_voided") == 1


async def test_void_sale_that_used_a_prize(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    """13.3: void a sale that used a prize -> prize back to active."""
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "10% de descuento"
    )
    berry = seeded.products["Berry Bliss"]
    sale = (
        await sell(
            owner,
            [(berry, 1)],
            customer_id=customer_id,
            prize_award_id=award_id,
            prize_target_product_id=berry,
        )
    ).json()
    await void(owner, sale["id"])
    row = owner_conn.execute(
        "SELECT status, redeemed_at, redeemed_sale_id, redeemed_by FROM prize_award"
    ).fetchone()
    assert row == ("active", None, None, None)
    assert events(owner_conn, "prize_restored") == 1
    # The old line stays on the void sale as history; the prize can be used again.
    again = await sell(
        owner,
        [(berry, 1)],
        customer_id=customer_id,
        prize_award_id=award_id,
        prize_target_product_id=berry,
    )
    assert again.status_code == 201


async def test_void_welcome_sale_with_other_same_day_sale(
    owner, open_workday, seeded, owner_conn, customer_client
):
    """13.3: reconcile creates a new welcome spin from the other sale."""
    first = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    second = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    await register(customer_client, claim_token(owner_conn, first["id"]))
    await customer_client.post(
        "/api/c/claim", json={"claim_token": claim_token(owner_conn, second["id"])}
    )
    await void(owner, first["id"])
    rows = spins(owner_conn)
    assert [(r[0], r[2]) for r in rows] == [
        ("welcome", "void"),
        ("welcome", "available"),
    ]
    assert rows[1][3] == second["id"]
    assert (await customer_client.get("/api/c/me")).json()["purchases"] == 1


async def test_void_sale_that_completed_milestone(
    owner, open_workday, seeded, owner_conn, customer_client
):
    """13.3: void the sale that completed milestone 5 -> milestone void, purchases=4."""
    customer_id = make_customer(owner_conn, seeded.business_id)
    add_past_purchases(owner_conn, seeded, customer_id, 4)
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    r = await customer_client.post(
        "/api/c/identify/confirm",
        json={
            "phone": "3101234567",
            "claim_token": claim_token(owner_conn, sale["id"]),
        },
    )
    assert [s["milestone_n"] for s in r.json()["new_spins"]] == [5]
    await void(owner, sale["id"])
    milestone = [s for s in spins(owner_conn) if s[0] == "milestone"]
    assert [s[2] for s in milestone] == ["void"]
    welcome = [s for s in spins(owner_conn) if s[0] == "welcome"]
    assert [s[2] for s in welcome] == ["available"]
    assert (await customer_client.get("/api/c/me")).json()["purchases"] == 4


async def test_void_leaves_redeemed_prize(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    _, award_id, sale_id = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Cold foam o topping extra"
    )
    await owner.post(
        f"/api/op/sales/{sale_id}/redeem-prize", json={"prize_award_id": award_id}
    )
    # Void the sale that unlocked the spin AND used the prize.
    await void(owner, sale_id)
    assert events(owner_conn, "void_left_redeemed_prize") == 1
    # Step 4 still restores the prize used in this sale.
    assert prize_status(owner_conn, award_id) == "active"


async def test_operator_cannot_void_closed_workday_sale(
    owner, operator, open_workday, seeded
):
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    await owner.post("/api/op/workdays/current/close")
    r = await void(operator, sale["id"])
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"
    r = await void(owner, sale["id"])
    assert r.status_code == 200


async def test_operator_can_void_open_workday_sale(operator, open_workday, seeded):
    sale = (await sell(operator, [(seeded.products["Berry Bliss"], 1)])).json()
    assert (await void(operator, sale["id"])).status_code == 200


async def test_unlink(owner, open_workday, seeded, owner_conn, customer_client):
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    await register(customer_client, claim_token(owner_conn, sale["id"]))
    r = await owner.post(f"/api/op/sales/{sale['id']}/unlink")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"
    assert r.json()["customer"] is None
    assert r.json()["claim_method"] is None
    assert [s[2] for s in spins(owner_conn)] == ["void"]
    assert events(owner_conn, "sale_unlinked") == 1
    assert (await customer_client.get("/api/c/me")).json()["purchases"] == 0
    # Back to paid: it can be linked again.
    status = (await owner.get(f"/api/op/sales/{sale['id']}/status")).json()
    assert status == {"status": "paid", "customer": None}


async def test_unlink_sale_with_prize(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    """13.3: unlink a sale with a prize -> sale_has_prize."""
    _, award_id, sale_id = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Cold foam o topping extra"
    )
    await owner.post(
        f"/api/op/sales/{sale_id}/redeem-prize", json={"prize_award_id": award_id}
    )
    r = await owner.post(f"/api/op/sales/{sale_id}/unlink")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "sale_has_prize"


async def test_unlink_needs_claimed_sale(owner, open_workday, seeded):
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    r = await owner.post(f"/api/op/sales/{sale['id']}/unlink")
    assert r.json()["error"]["code"] == "sale_not_linkable"
