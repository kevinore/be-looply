"""13.2 flows F1-F3, 11.10 identity, 11.11 wheel, 13.3 edge cases."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from tests.api.conftest import (
    add_past_purchases,
    claim_token,
    make_client,
    make_customer,
    register,
    sell,
)


async def new_sale(owner, seeded, owner_conn, qty=1):
    sale = (await sell(owner, [(seeded.products["Berry Bliss"], qty)])).json()
    return sale, claim_token(owner_conn, sale["id"])


async def test_f1_first_purchase(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    sale, token = await new_sale(owner, seeded, owner_conn, qty=2)

    preview = (await customer_client.get(f"/api/client/claims/{token}")).json()
    assert preview["state"] == "claimable"
    assert preview["sale"]["items_count"] == 2
    assert preview["sale"]["total_cop"] == 28000
    assert preview["business"]["name"] == "Test Business"

    r = await register(customer_client, token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counted"] is True
    assert [s["reason"] for s in body["new_spins"]] == ["welcome"]
    card = body["card"]
    assert card["customer"]["phone_last4"] == "4567"
    assert card["purchases"] == 1
    assert card["progress"] == 1
    assert card["purchases_to_next_spin"] == 4
    assert "client_session" in customer_client.cookies

    spin_id = body["new_spins"][0]["id"]
    r = await customer_client.post(f"/api/client/spins/{spin_id}/spin")
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["prize_award"]["name"] == "10% de descuento"
    assert result["segment_index"] == 0
    expires = datetime.fromisoformat(result["prize_award"]["expires_at"])
    assert abs(expires - (datetime.now(UTC) + timedelta(days=90))) < timedelta(
        minutes=1
    )
    assert result["card"]["available_spins"] == []
    assert [p["name"] for p in result["card"]["active_prizes"]] == ["10% de descuento"]

    prize = (
        await customer_client.get(f"/api/client/prizes/{result['prize_award']['id']}")
    ).json()
    assert prize["status"] == "active"

    preview = (await customer_client.get(f"/api/client/claims/{token}")).json()
    assert preview["state"] == "already_claimed"

    status = (await owner.get(f"/api/admin/sales/{sale['id']}/status")).json()
    assert status["customer"]["alias"] == "Ana"
    assert status["customer"]["active_prizes"][0]["name"] == "10% de descuento"

    stored = owner_conn.execute(
        "SELECT phone, consent_version FROM customer"
    ).fetchone()
    assert stored == ("+573101234567", "test-v1")


async def test_f2_open_session_milestone(
    owner, open_workday, seeded, owner_conn, customer_client
):
    """F2: 4 purchases in 4 workdays -> new workday -> claim -> purchases=5, milestone 5."""
    customer_id = make_customer(owner_conn, seeded.business_id)
    add_past_purchases(owner_conn, seeded, customer_id, 4)
    _, token = await new_sale(owner, seeded, owner_conn)
    # Log in the customer through identity confirmation on a first sale.
    _, first = await new_sale(owner, seeded, owner_conn)
    r = await customer_client.post(
        "/api/client/identify/confirm",
        json={"phone": "3101234567", "claim_token": first},
    )
    assert r.json()["card"]["purchases"] == 5
    assert [s["milestone_n"] for s in r.json()["new_spins"]] == [5]

    # Same workday again: one more stamp (R8, per sale), next milestone is 10.
    r = await customer_client.post("/api/client/claim", json={"claim_token": token})
    assert r.status_code == 200
    assert r.json()["counted"] is True
    assert r.json()["new_spins"] == []
    assert r.json()["card"]["purchases"] == 6
    assert r.json()["card"]["progress"] == 1


async def test_f2_same_day_second_sale(
    owner, open_workday, seeded, owner_conn, customer_client
):
    """R8: every claimed sale is a stamp, even minutes apart on the same day."""
    _, first = await new_sale(owner, seeded, owner_conn)
    _, second = await new_sale(owner, seeded, owner_conn)
    await register(customer_client, first)
    r = await customer_client.post("/api/client/claim", json={"claim_token": second})
    assert r.json()["counted"] is True
    assert r.json()["new_spins"] == []  # the welcome spin is only once
    assert r.json()["card"]["purchases"] == 2


async def test_stamp_per_sale_not_per_item(
    owner, open_workday, seeded, owner_conn, customer_client
):
    """R8: a sale with many items is still one stamp."""
    sale = (
        await sell(
            owner,
            [(seeded.products["Berry Bliss"], 3), (seeded.products["Passion Soda"], 2)],
        )
    ).json()
    r = await register(customer_client, claim_token(owner_conn, sale["id"]))
    assert r.json()["card"]["purchases"] == 1


async def test_milestone_reached_on_one_day(
    owner, open_workday, seeded, owner_conn, customer_client
):
    """R8 + R10: five sales in a single workday reach milestone 5."""
    _, first = await new_sale(owner, seeded, owner_conn)
    await register(customer_client, first)
    for _ in range(4):
        _, token = await new_sale(owner, seeded, owner_conn)
        r = await customer_client.post("/api/client/claim", json={"claim_token": token})
    assert r.json()["card"]["purchases"] == 5
    assert [s["milestone_n"] for s in r.json()["new_spins"]] == [5]


async def test_void_second_same_day_sale_removes_its_stamp(
    owner, open_workday, seeded, owner_conn, customer_client
):
    _, first = await new_sale(owner, seeded, owner_conn)
    second, token = await new_sale(owner, seeded, owner_conn)
    await register(customer_client, first)
    await customer_client.post("/api/client/claim", json={"claim_token": token})
    r = await owner.post(
        f"/api/admin/sales/{second['id']}/void", json={"reason": "duplicada"}
    )
    assert r.status_code == 200, r.text
    assert (await customer_client.get("/api/client/me")).json()["purchases"] == 1


async def test_per_workday_rule_still_works(
    owner, open_workday, seeded, owner_conn, customer_client, monkeypatch
):
    """The previous R8 (one stamp per workday) stays available in stamps.py."""
    from app.services import stamps

    monkeypatch.setattr(stamps, "STAMP_RULE", stamps.StampRule.PER_WORKDAY)
    _, first = await new_sale(owner, seeded, owner_conn)
    _, second = await new_sale(owner, seeded, owner_conn)
    await register(customer_client, first)
    r = await customer_client.post("/api/client/claim", json={"claim_token": second})
    assert r.json()["counted"] is False
    assert r.json()["card"]["purchases"] == 1


async def test_f3_no_session(owner, open_workday, seeded, owner_conn, customer_client):
    """F3: register with an existing phone -> 409 with alias -> confirm -> new session."""
    customer_id = make_customer(owner_conn, seeded.business_id)
    add_past_purchases(owner_conn, seeded, customer_id, 1)
    _, token = await new_sale(owner, seeded, owner_conn)

    r = await register(customer_client, token, alias="Otra")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "customer_exists"
    assert err["extra"] == {"alias": "Ana", "phone_last4": "4567"}

    r = await customer_client.post(
        "/api/client/identify/confirm",
        json={"phone": "+57 310-123-4567", "claim_token": token},
    )
    assert r.status_code == 200, r.text
    assert r.json()["counted"] is True
    assert r.json()["new_spins"] == []  # already had the welcome spin
    assert r.json()["card"]["purchases"] == 2
    assert (await customer_client.get("/api/client/me")).status_code == 200
    assert owner_conn.execute("SELECT count(*) FROM customer").fetchone()[0] == 1


async def test_identify_unknown_phone(
    owner, open_workday, seeded, owner_conn, customer_client
):
    _, token = await new_sale(owner, seeded, owner_conn)
    r = await customer_client.post(
        "/api/client/identify/confirm",
        json={"phone": "3109999999", "claim_token": token},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "customer_not_found"


async def test_register_without_or_with_expired_token(
    owner, open_workday, seeded, owner_conn, customer_client
):
    r = await customer_client.post(
        "/api/client/register",
        json={"phone": "3101234567", "alias": "Ana", "consent": True},
    )
    assert r.json()["error"]["code"] == "validation_error"
    r = await register(customer_client, "no-such-token")
    assert r.json()["error"]["code"] == "claim_not_found"

    _, token = await new_sale(owner, seeded, owner_conn)
    owner_conn.execute("UPDATE sale SET claim_expires_at = now() - interval '1 minute'")
    owner_conn.commit()
    r = await register(customer_client, token)
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "claim_expired"
    assert owner_conn.execute("SELECT count(*) FROM customer").fetchone()[0] == 0


async def test_register_without_consent(
    owner, open_workday, seeded, owner_conn, customer_client
):
    _, token = await new_sale(owner, seeded, owner_conn)
    r = await customer_client.post(
        "/api/client/register",
        json={
            "phone": "3101234567",
            "alias": "Ana",
            "consent": False,
            "claim_token": token,
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "consent_required"
    assert owner_conn.execute("SELECT count(*) FROM customer").fetchone()[0] == 0


async def test_register_invalid_phone_and_alias(
    owner, open_workday, seeded, owner_conn, customer_client
):
    _, token = await new_sale(owner, seeded, owner_conn)
    r = await register(customer_client, token, phone="6011234567")
    assert r.json()["error"]["code"] == "invalid_phone"
    r = await register(customer_client, token, alias="  A  ")
    assert r.json()["error"]["code"] == "validation_error"
    r = await register(customer_client, token, alias="  Ana María  ")
    assert r.json()["card"]["customer"]["alias"] == "Ana María"


async def test_claim_already_claimed_and_voided(
    owner, open_workday, seeded, owner_conn, customer_client
):
    _, token = await new_sale(owner, seeded, owner_conn)
    await register(customer_client, token)
    r = await customer_client.post("/api/client/claim", json={"claim_token": token})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "claim_already_claimed"

    other, other_token = await new_sale(owner, seeded, owner_conn)
    await owner.post(f"/api/admin/sales/{other['id']}/void", json={"reason": "error"})
    r = await customer_client.post(
        "/api/client/claim", json={"claim_token": other_token}
    )
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "claim_voided"
    preview = (await customer_client.get(f"/api/client/claims/{other_token}")).json()
    assert preview["state"] == "voided"


async def test_preview_not_found(customer_client, seeded):
    r = await customer_client.get("/api/client/claims/nope")
    assert r.status_code == 200
    assert r.json() == {"state": "not_found", "sale": None, "business": None}


async def test_concurrent_claims_same_token(owner, open_workday, seeded, owner_conn):
    """13.3: two simultaneous claims of the same token -> one wins."""
    _, t1 = await new_sale(owner, seeded, owner_conn)
    _, t2 = await new_sale(owner, seeded, owner_conn)
    _, shared = await new_sale(owner, seeded, owner_conn)
    async with make_client() as ana, make_client() as bea:
        await register(ana, t1, phone="3101234567", alias="Ana")
        await register(bea, t2, phone="3107654321", alias="Bea")
        results = await asyncio.gather(
            ana.post("/api/client/claim", json={"claim_token": shared}),
            bea.post("/api/client/claim", json={"claim_token": shared}),
        )
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] == "claim_already_claimed"


async def test_spin_twice_same_prize(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    _, token = await new_sale(owner, seeded, owner_conn)
    spin_id = (await register(customer_client, token)).json()["new_spins"][0]["id"]
    first = (await customer_client.post(f"/api/client/spins/{spin_id}/spin")).json()
    rng("Bebida gratis")
    second = (await customer_client.post(f"/api/client/spins/{spin_id}/spin")).json()
    assert first["prize_award"] == second["prize_award"]
    assert owner_conn.execute("SELECT count(*) FROM prize_award").fetchone()[0] == 1


async def test_spin_of_another_customer(owner, open_workday, seeded, owner_conn, rng):
    _, t1 = await new_sale(owner, seeded, owner_conn)
    _, t2 = await new_sale(owner, seeded, owner_conn)
    async with make_client() as ana, make_client() as bea:
        spin_id = (await register(ana, t1)).json()["new_spins"][0]["id"]
        await register(bea, t2, phone="3107654321", alias="Bea")
        r = await bea.post(f"/api/client/spins/{spin_id}/spin")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "spin_not_found"
        r = await bea.post(f"/api/client/spins/{uuid4()}/spin")
        assert r.json()["error"]["code"] == "spin_not_found"


async def test_prize_of_another_customer(owner, open_workday, seeded, owner_conn, rng):
    _, t1 = await new_sale(owner, seeded, owner_conn)
    _, t2 = await new_sale(owner, seeded, owner_conn)
    async with make_client() as ana, make_client() as bea:
        spin_id = (await register(ana, t1)).json()["new_spins"][0]["id"]
        award_id = (await ana.post(f"/api/client/spins/{spin_id}/spin")).json()[
            "prize_award"
        ]["id"]
        await register(bea, t2, phone="3107654321", alias="Bea")
        r = await bea.get(f"/api/client/prizes/{award_id}")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "prize_not_found"


async def test_void_spin_not_available(
    owner, open_workday, seeded, owner_conn, customer_client
):
    sale, token = await new_sale(owner, seeded, owner_conn)
    spin_id = (await register(customer_client, token)).json()["new_spins"][0]["id"]
    await owner.post(f"/api/admin/sales/{sale['id']}/void", json={"reason": "error"})
    r = await customer_client.post(f"/api/client/spins/{spin_id}/spin")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "spin_not_available"


async def test_expired_prize_shows_expired(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    _, token = await new_sale(owner, seeded, owner_conn)
    spin_id = (await register(customer_client, token)).json()["new_spins"][0]["id"]
    award_id = (await customer_client.post(f"/api/client/spins/{spin_id}/spin")).json()[
        "prize_award"
    ]["id"]
    owner_conn.execute(
        "UPDATE prize_award SET expires_at = now() - interval '1 second'"
    )
    owner_conn.commit()
    r = await customer_client.get(f"/api/client/prizes/{award_id}")
    assert r.json()["status"] == "expired"
    assert (await customer_client.get("/api/client/me")).json()["active_prizes"] == []


async def test_wheel_without_weights(client, seeded, owner_conn):
    owner_conn.execute(
        "UPDATE prize_catalog SET active = false WHERE name = 'Bebida gratis'"
    )
    owner_conn.commit()
    r = await client.get("/api/client/wheel")
    segments = r.json()["segments"]
    assert [s["short_label"] for s in segments] == [
        "10% dto",
        "Topping",
        "20% dto",
        "50% dto",
    ]
    assert all(set(s) == {"id", "short_label", "color"} for s in segments)
    assert "weight" not in r.text


async def test_public_business(client, seeded):
    r = await client.get("/api/client/business")
    assert r.json() == {
        "name": "Test Business",
        "slug": "test-biz",
        "branding": {"display_name": "Test Business"},
        "privacy_policy_version": "test-v1",
    }


async def test_history_and_logout(
    owner, open_workday, seeded, owner_conn, customer_client
):
    _, token = await new_sale(owner, seeded, owner_conn, qty=2)
    await register(customer_client, token)
    history = (await customer_client.get("/api/client/history")).json()
    assert len(history) == 1
    assert history[0]["total_cop"] == 28000
    assert history[0]["items"][0]["label"] == "Berry Bliss"
    assert history[0]["prize_used"] is None

    assert (await customer_client.post("/api/client/logout")).status_code == 204
    r = await customer_client.get("/api/client/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "not_authenticated"


async def test_customer_cookie_on_operator_api(
    owner, open_workday, seeded, owner_conn, customer_client
):
    _, token = await new_sale(owner, seeded, owner_conn)
    await register(customer_client, token)
    r = await customer_client.get("/api/admin/auth/me")
    assert r.status_code == 401


async def test_register_rate_limit_per_token(customer_client, seeded):
    for _ in range(5):
        await register(customer_client, "same-token")
    r = await register(customer_client, "same-token")
    assert r.status_code == 429
