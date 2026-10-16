"""Product categories, and products that don't earn stamps or take prizes (0007),
and prizes limited to one category (0008).

Owner decision (2026-10-14): ice creams are a section of their own, buying only
ice cream earns no stamp. Owner decision (2026-10-16): ice creams take prizes, but
only the prizes of their category (e.g. a free ice cream, never a drink discount).
"""

import copy

import pytest

from scripts.seed import seed
from tests.api.conftest import (
    OWNER_URL,
    TEST_DATA,
    claim_token,
    customer_with_prize,
    register,
    sell,
)

ICE = {"category": "Helados", "earns_stamp": False, "prize_eligible": False}


def data_with_ice_cream() -> dict:
    data = copy.deepcopy(TEST_DATA)
    data["categories"] = [
        {"name": "Bebidas", "sort_order": 1},
        {"name": "Helados", "sort_order": 2},
    ]
    for p in data["products"]:
        p["category"] = "Bebidas"
    data["products"].append(
        {"sort_order": 1, "name": "Paleta", "price_cop": 5000, "cost_cop": None, **ICE}
    )
    return data


@pytest.fixture
async def paleta(owner, seeded):
    seed(OWNER_URL, data_with_ice_cream())
    products = (await owner.get("/api/admin/products")).json()
    return next(p["id"] for p in products if p["name"] == "Paleta")


async def test_products_grouped_by_category(owner, paleta):
    products = (await owner.get("/api/admin/products")).json()
    # Category order first (Bebidas, then Helados), product order inside each.
    assert [(p["category"], p["name"]) for p in products] == [
        ("Bebidas", "Berry Bliss"),
        ("Bebidas", "Green Chai Latte"),
        ("Bebidas", "Passion Soda"),
        ("Helados", "Paleta"),
    ]
    paleta_row = products[-1]
    assert paleta_row["prize_eligible"] is False
    assert products[0]["prize_eligible"] is True


async def test_ice_cream_alone_earns_no_stamp(
    owner, open_workday, paleta, seeded, owner_conn, customer_client
):
    sale = (await sell(owner, [(paleta, 2)])).json()
    r = await register(customer_client, claim_token(owner_conn, sale["id"]))
    assert r.status_code == 200, r.text
    body = r.json()
    # The sale is linked to the customer, but adds nothing to the card.
    assert body["counted"] is False
    assert body["stamp_eligible"] is False
    assert body["card"]["purchases"] == 0
    assert body["new_spins"] == []  # no welcome spin without a counted purchase
    history = (await customer_client.get("/api/client/history")).json()
    assert [h["id"] for h in history] == [sale["id"]]

    # A drink, even with ice cream in the same sale, earns the stamp.
    berry = seeded.products["Berry Bliss"]
    mixed = (await sell(owner, [(berry, 1), (paleta, 1)])).json()
    r = await customer_client.post(
        "/api/client/claim", json={"claim_token": claim_token(owner_conn, mixed["id"])}
    )
    body = r.json()
    assert (body["counted"], body["stamp_eligible"]) == (True, True)
    assert body["card"]["purchases"] == 1
    assert [s["reason"] for s in body["new_spins"]] == ["welcome"]


async def test_earns_stamp_is_copied_at_sale_time(
    owner, open_workday, paleta, owner_conn
):
    sale = (await sell(owner, [(paleta, 1)])).json()
    # Changing the product later does not change the sale already made.
    owner_conn.execute("UPDATE product SET earns_stamp = true WHERE name = 'Paleta'")
    owner_conn.commit()
    row = owner_conn.execute(
        "SELECT earns_stamp FROM sale WHERE id = %s", (sale["id"],)
    ).fetchone()
    assert row == (False,)


async def test_no_prize_on_ice_cream_at_creation(
    owner, open_workday, paleta, seeded, owner_conn, customer_client, rng
):
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "10% de descuento"
    )
    r = await sell(
        owner,
        [(paleta, 1), (seeded.products["Berry Bliss"], 1)],
        customer_id=customer_id,
        prize_award_id=award_id,
        prize_target_product_id=paleta,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "prize_target_invalid"


async def test_no_free_ice_cream_on_paid_sale(
    owner, open_workday, paleta, seeded, owner_conn, customer_client, rng
):
    _, award_id, sale_id = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Bebida gratis"
    )
    r = await owner.post(
        f"/api/admin/sales/{sale_id}/redeem-prize",
        json={"prize_award_id": award_id, "product_id": str(paleta)},
    )
    assert r.json()["error"]["code"] == "prize_target_invalid"


async def test_no_extra_item_on_ice_cream_only_sale(
    owner, open_workday, paleta, seeded, owner_conn, customer_client, rng
):
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Cold foam o topping extra"
    )
    sale = (await sell(owner, [(paleta, 1)], customer_id=customer_id)).json()
    r = await owner.post(
        f"/api/admin/sales/{sale['id']}/redeem-prize",
        json={"prize_award_id": award_id},
    )
    assert r.json()["error"]["code"] == "prize_target_invalid"


async def test_unknown_category_in_seed_fails(seeded):
    data = data_with_ice_cream()
    data["products"][-1]["category"] = "Nope"
    with pytest.raises(SystemExit):
        seed(OWNER_URL, data)


# ---- Prizes limited to a category (0008) ----


def set_prize_category(conn, prize_name, category_name) -> None:
    conn.execute(
        "UPDATE prize_catalog SET category_id = "
        "(SELECT id FROM product_category WHERE name = %s) WHERE name = %s",
        (category_name, prize_name),
    )
    conn.commit()


@pytest.fixture
async def paleta_takes_prizes(paleta, owner_conn):
    owner_conn.execute(
        "UPDATE product SET prize_eligible = true WHERE id = %s", (paleta,)
    )
    owner_conn.commit()
    return paleta


async def test_products_carry_their_category_id(owner, paleta, owner_conn):
    products = (await owner.get("/api/admin/products")).json()
    helados = owner_conn.execute(
        "SELECT id FROM product_category WHERE name = 'Helados'"
    ).fetchone()[0]
    assert next(p for p in products if p["id"] == paleta)["category_id"] == str(helados)


async def test_ice_cream_prize_applies_only_to_ice_cream(
    owner, open_workday, paleta_takes_prizes, seeded, owner_conn, customer_client, rng
):
    paleta = paleta_takes_prizes
    set_prize_category(owner_conn, "Bebida gratis", "Helados")
    _, award_id, sale_id = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Bebida gratis"
    )
    # Not a drink: the prize is for ice creams.
    url = f"/api/admin/sales/{sale_id}/redeem-prize"
    berry = seeded.products["Berry Bliss"]
    r = await owner.post(
        url, json={"prize_award_id": award_id, "product_id": str(berry)}
    )
    assert r.json()["error"]["code"] == "prize_target_invalid"

    r = await owner.post(
        url, json={"prize_award_id": award_id, "product_id": str(paleta)}
    )
    assert r.status_code == 200, r.text
    line = next(i for i in r.json()["items"] if i["prize_award_id"] == award_id)
    assert (line["label"], line["unit_price_cop"], line["discount_cop"]) == (
        "Paleta",
        5000,
        5000,
    )


async def test_drink_prize_never_applies_to_ice_cream(
    owner, open_workday, paleta_takes_prizes, seeded, owner_conn, customer_client, rng
):
    paleta = paleta_takes_prizes
    set_prize_category(owner_conn, "10% de descuento", "Bebidas")
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "10% de descuento"
    )
    berry = seeded.products["Berry Bliss"]
    common = {"customer_id": customer_id, "prize_award_id": award_id}
    r = await sell(
        owner, [(paleta, 1), (berry, 1)], prize_target_product_id=paleta, **common
    )
    assert r.json()["error"]["code"] == "prize_target_invalid"

    r = await sell(
        owner, [(paleta, 1), (berry, 1)], prize_target_product_id=berry, **common
    )
    assert r.status_code == 201, r.text
    assert r.json()["total_cop"] == 5000 + 14000 - 1400


async def test_extra_item_needs_a_product_of_its_category(
    owner, open_workday, paleta_takes_prizes, seeded, owner_conn, customer_client, rng
):
    paleta = paleta_takes_prizes
    set_prize_category(owner_conn, "Cold foam o topping extra", "Helados")
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Cold foam o topping extra"
    )
    berry = seeded.products["Berry Bliss"]
    drinks_only = (await sell(owner, [(berry, 1)], customer_id=customer_id)).json()
    url = f"/api/admin/sales/{drinks_only['id']}/redeem-prize"
    r = await owner.post(url, json={"prize_award_id": award_id})
    assert r.json()["error"]["code"] == "prize_target_invalid"

    with_ice = (await sell(owner, [(paleta, 1)], customer_id=customer_id)).json()
    url = f"/api/admin/sales/{with_ice['id']}/redeem-prize"
    r = await owner.post(url, json={"prize_award_id": award_id})
    assert r.status_code == 200, r.text


async def test_seed_sets_prize_category(owner_conn, seeded):
    data = data_with_ice_cream()
    data["business"] = data["business"] | {"slug": "other-biz"}
    data["prize_catalog"][0]["category"] = "Helados"
    seed(OWNER_URL, data)
    rows = owner_conn.execute(
        "SELECT p.name, c.name FROM prize_catalog p "
        "JOIN business b ON b.id = p.business_id AND b.slug = 'other-biz' "
        "LEFT JOIN product_category c ON c.id = p.category_id"
    ).fetchall()
    assert dict(rows)["10% de descuento"] == "Helados"
    assert dict(rows)["Bebida gratis"] is None

    data["business"]["slug"] = "third-biz"
    data["prize_catalog"][0]["category"] = "Nope"
    with pytest.raises(SystemExit):
        seed(OWNER_URL, data)
