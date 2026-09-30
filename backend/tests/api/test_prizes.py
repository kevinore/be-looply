"""11.9 Prizes: F5, F6 and 13.3 edge cases."""

from tests.api.conftest import customer_with_prize, make_client, prize_status, sell


async def test_f5_saved_percent_prize(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    """F5: 10% over a 14000 drink -> 1400 off one unit, prize redeemed."""
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "10% de descuento"
    )
    berry = seeded.products["Berry Bliss"]
    r = await sell(
        owner,
        [(berry, 2)],
        customer_id=customer_id,
        prize_award_id=award_id,
        prize_target_product_id=berry,
    )
    assert r.status_code == 201, r.text
    sale = r.json()
    assert sale["items"][0]["discount_cop"] == 1400
    assert sale["items"][0]["prize_award_id"] == award_id
    assert sale["total_cop"] == 2 * 14000 - 1400
    assert sale["status"] == "claimed"
    assert prize_status(owner_conn, award_id) == "redeemed"
    history = (await customer_client.get("/api/c/history")).json()
    assert history[0]["prize_used"] == "10% de descuento"
    prize = (await customer_client.get(f"/api/c/prizes/{award_id}")).json()
    assert prize["status"] == "redeemed"


async def test_f5_cap(owner, open_workday, seeded, owner_conn, customer_client, rng):
    """F5 cap: 50% over 16000 with cap 16000 -> 8000."""
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "50% de descuento"
    )
    latte = seeded.products["Green Chai Latte"]
    sale = (
        await sell(
            owner,
            [(latte, 1)],
            customer_id=customer_id,
            prize_award_id=award_id,
            prize_target_product_id=latte,
        )
    ).json()
    assert sale["items"][0]["discount_cop"] == 8000
    assert sale["total_cop"] == 8000


async def test_percent_off_capped_by_max_value(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    owner_conn.execute(
        "UPDATE prize_catalog SET max_value_cop = 5000 WHERE name = '50% de descuento'"
    )
    owner_conn.commit()
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "50% de descuento"
    )
    latte = seeded.products["Green Chai Latte"]
    sale = (
        await sell(
            owner,
            [(latte, 1)],
            customer_id=customer_id,
            prize_award_id=award_id,
            prize_target_product_id=latte,
        )
    ).json()
    assert sale["items"][0]["discount_cop"] == 5000


async def test_free_item_at_creation(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Bebida gratis"
    )
    berry = seeded.products["Berry Bliss"]
    sale = (
        await sell(
            owner,
            [(berry, 2)],
            customer_id=customer_id,
            prize_award_id=award_id,
            prize_target_product_id=berry,
        )
    ).json()
    assert sale["items"][0]["discount_cop"] == 14000
    assert sale["total_cop"] == 14000


async def test_extra_item_at_creation(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Cold foam o topping extra"
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
    extra = sale["items"][1]
    assert extra == {
        "product_id": None,
        "label": "Cold foam o topping extra",
        "qty": 1,
        "unit_price_cop": 0,
        "discount_cop": 0,
        "prize_award_id": award_id,
    }
    assert sale["total_cop"] == 14000


async def test_f6_immediate_extra_on_paid_sale(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    """F6: spin -> extra_item -> redeem on the paid sale -> $0 line, same total (R14)."""
    _, award_id, sale_id = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Cold foam o topping extra"
    )
    r = await owner.post(
        f"/api/op/sales/{sale_id}/redeem-prize", json={"prize_award_id": award_id}
    )
    assert r.status_code == 200, r.text
    sale = r.json()
    assert sale["total_cop"] == 14000
    assert sale["items"][1]["unit_price_cop"] == 0
    assert sale["items"][1]["prize_award_id"] == award_id
    assert prize_status(owner_conn, award_id) == "redeemed"


async def test_f6_free_item_on_paid_sale(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    _, award_id, sale_id = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Bebida gratis"
    )
    berry = seeded.products["Berry Bliss"]
    r = await owner.post(
        f"/api/op/sales/{sale_id}/redeem-prize",
        json={"prize_award_id": award_id, "product_id": str(berry)},
    )
    sale = r.json()
    assert sale["total_cop"] == 14000  # net $0 line
    free = sale["items"][1]
    assert free["product_id"] == str(berry)
    assert free["unit_price_cop"] == 14000
    assert free["discount_cop"] == 14000


async def test_free_item_on_paid_sale_cap_below_price(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    owner_conn.execute(
        "UPDATE prize_catalog SET max_value_cop = 10000 WHERE name = 'Bebida gratis'"
    )
    owner_conn.commit()
    _, award_id, sale_id = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Bebida gratis"
    )
    r = await owner.post(
        f"/api/op/sales/{sale_id}/redeem-prize",
        json={
            "prize_award_id": award_id,
            "product_id": str(seeded.products["Berry Bliss"]),
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "prize_target_invalid"
    assert prize_status(owner_conn, award_id) == "active"


async def test_f6_percent_off_on_paid_sale(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    """F6: percent_off over a paid sale -> discount_needs_new_sale (R18)."""
    _, award_id, sale_id = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "10% de descuento"
    )
    r = await owner.post(
        f"/api/op/sales/{sale_id}/redeem-prize", json={"prize_award_id": award_id}
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "discount_needs_new_sale"


async def test_two_prizes_in_one_sale(owner, open_workday, seeded, owner_conn, rng):
    """13.3: second prize on the same sale -> prize_already_in_sale (R16)."""
    async with make_client() as c:
        customer_id, first, sale_id = await customer_with_prize(
            owner, seeded, owner_conn, c, rng, "Cold foam o topping extra"
        )
        # A second prize for the same customer (a milestone spin inserted directly).
        spin_id = owner_conn.execute(
            "INSERT INTO spin (business_id, customer_id, reason, milestone_n, "
            "unlocked_by_sale_id) VALUES (%s, %s, 'milestone', 5, %s) RETURNING id",
            (seeded.business_id, customer_id, sale_id),
        ).fetchone()[0]
        owner_conn.commit()
        second = (await c.post(f"/api/c/spins/{spin_id}/spin")).json()["prize_award"][
            "id"
        ]
    r = await owner.post(
        f"/api/op/sales/{sale_id}/redeem-prize", json={"prize_award_id": first}
    )
    assert r.status_code == 200
    r = await owner.post(
        f"/api/op/sales/{sale_id}/redeem-prize", json={"prize_award_id": second}
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "prize_already_in_sale"
    assert prize_status(owner_conn, second) == "active"


async def test_prize_already_used(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    customer_id, award_id, sale_id = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Cold foam o topping extra"
    )
    await owner.post(
        f"/api/op/sales/{sale_id}/redeem-prize", json={"prize_award_id": award_id}
    )
    berry = seeded.products["Berry Bliss"]
    r = await sell(
        owner,
        [(berry, 1)],
        customer_id=customer_id,
        prize_award_id=award_id,
        prize_target_product_id=berry,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "prize_not_active"


async def test_expired_prize(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "10% de descuento"
    )
    owner_conn.execute(
        "UPDATE prize_award SET expires_at = now() - interval '1 second'"
    )
    owner_conn.commit()
    berry = seeded.products["Berry Bliss"]
    r = await sell(
        owner,
        [(berry, 1)],
        customer_id=customer_id,
        prize_award_id=award_id,
        prize_target_product_id=berry,
    )
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "prize_expired"
    assert owner_conn.execute("SELECT count(*) FROM sale").fetchone()[0] == 1


async def test_prize_of_another_customer(owner, open_workday, seeded, owner_conn, rng):
    async with make_client() as ana, make_client() as bea:
        _, award_id, _ = await customer_with_prize(
            owner, seeded, owner_conn, ana, rng, "10% de descuento"
        )
        bea_id, _, _ = await customer_with_prize(
            owner, seeded, owner_conn, bea, rng, "10% de descuento", phone="3107654321"
        )
    berry = seeded.products["Berry Bliss"]
    r = await sell(
        owner,
        [(berry, 1)],
        customer_id=bea_id,
        prize_award_id=award_id,
        prize_target_product_id=berry,
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "prize_not_found"


async def test_prize_target_not_in_items(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "10% de descuento"
    )
    r = await sell(
        owner,
        [(seeded.products["Berry Bliss"], 1)],
        customer_id=customer_id,
        prize_award_id=award_id,
        prize_target_product_id=seeded.products["Green Chai Latte"],
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "prize_target_invalid"


async def test_redeem_needs_claimed_sale_in_open_workday(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    _, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Cold foam o topping extra"
    )
    anonymous = (await sell(owner, [(seeded.products["Berry Bliss"], 1)])).json()
    r = await owner.post(
        f"/api/op/sales/{anonymous['id']}/redeem-prize",
        json={"prize_award_id": award_id},
    )
    assert r.json()["error"]["code"] == "sale_not_linkable"


async def test_pending_prizes_filters(owner, open_workday, seeded, owner_conn, rng):
    async with make_client() as ana, make_client() as bea:
        await customer_with_prize(owner, seeded, owner_conn, ana, rng, "Bebida gratis")
        await customer_with_prize(
            owner, seeded, owner_conn, bea, rng, "10% de descuento", phone="3107654321"
        )
    owner_conn.execute(
        "UPDATE prize_award SET expires_at = now() + interval '3 days' "
        "WHERE prize_id = (SELECT id FROM prize_catalog WHERE name = '10% de descuento')"
    )
    owner_conn.commit()

    all_ = (await owner.get("/api/op/prizes/pending")).json()
    assert [p["prize_name"] for p in all_] == ["10% de descuento", "Bebida gratis"]
    assert set(all_[0]) == {
        "prize_award_id",
        "customer_id",
        "alias",
        "phone_last4",
        "prize_name",
        "prize_type",
        "awarded_at",
        "expires_at",
    }
    free = (await owner.get("/api/op/prizes/pending?filter=free")).json()
    assert [p["prize_name"] for p in free] == ["Bebida gratis"]
    expiring = (await owner.get("/api/op/prizes/pending?filter=expiring")).json()
    assert [p["prize_name"] for p in expiring] == ["10% de descuento"]
    bad = await owner.get("/api/op/prizes/pending?filter=nope")
    assert bad.json()["error"]["code"] == "validation_error"


async def test_catalog_owner_only(owner, operator):
    r = await operator.get("/api/op/prizes/catalog")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"
    r = await owner.get("/api/op/prizes/catalog")
    assert r.status_code == 200
    assert [p["weight"] for p in r.json()] == [40, 25, 20, 10, 5]
