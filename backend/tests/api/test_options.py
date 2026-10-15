"""Product options (migration 0005, services/options.py)."""

import copy
import csv
import io
from uuid import uuid4

import pytest

from app.core.time import local_today
from scripts.seed import seed
from tests.api.conftest import (
    OWNER_URL,
    TEST_DATA,
    claim_token,
    customer_with_prize,
    register,
    sell,
)

OPTION_GROUPS = [
    {
        "name": "Base",
        "sort_order": 1,
        "options": [
            {"name": "Yogurt griego", "sort_order": 1},
            {"name": "Avena", "sort_order": 2, "price_delta_cop": 1000},
            {"name": "Coco", "sort_order": 3, "active": False},
        ],
    },
    {
        "name": "Té",
        "sort_order": 2,
        "options": [
            {"name": "Chai pistacho", "sort_order": 1},
            {"name": "Matcha", "sort_order": 2},
        ],
    },
    # Optional, several choices; not linked to the layered product.
    {
        "name": "Toppings",
        "min_select": 0,
        "max_select": 2,
        "sort_order": 3,
        "options": [{"name": "Chía"}, {"name": "Granola"}],
    },
]

LAYERED = {
    "sort_order": 4,
    "name": "Sunset Passion",
    "price_cop": 14000,
    "cost_cop": 5000,
    "description": "Frutos amarillos",
    "option_groups": ["Base", "Té"],
}


def seed_data(**changes) -> dict:
    data = copy.deepcopy(TEST_DATA)
    data["option_groups"] = copy.deepcopy(OPTION_GROUPS)
    data["products"] = [*data["products"], copy.deepcopy(LAYERED)]
    data.update(changes)
    return data


@pytest.fixture
async def menu(owner, seeded) -> dict:
    """Seeds the option groups and returns {product name: product} from the API."""
    seed(OWNER_URL, seed_data())
    products = (await owner.get("/api/op/products")).json()
    return {p["name"]: p for p in products}


def option_ids(product: dict) -> dict[str, str]:
    return {o["name"]: o["id"] for g in product["option_groups"] for o in g["options"]}


def line(product: dict, qty: int, *names: str) -> dict:
    ids = option_ids(product)
    return {
        "product_id": product["id"],
        "qty": qty,
        "option_ids": [ids[n] for n in names],
    }


async def post_sale(client, items: list[dict], **extra):
    body = {"items": items, "payment_method": "cash", **extra}
    return await client.post(
        "/api/op/sales", json=body, headers={"Idempotency-Key": str(uuid4())}
    )


async def test_products_include_option_groups(menu):
    p = menu["Sunset Passion"]
    assert p["description"] == "Frutos amarillos"
    assert [g["name"] for g in p["option_groups"]] == ["Base", "Té"]
    base = p["option_groups"][0]
    assert (base["min_select"], base["max_select"]) == (1, 1)
    # Inactive choices are never offered.
    assert [(o["name"], o["price_delta_cop"]) for o in base["options"]] == [
        ("Yogurt griego", 0),
        ("Avena", 1000),
    ]
    assert menu["Passion Soda"]["option_groups"] == []
    assert menu["Passion Soda"]["description"] is None


async def test_sale_with_options(owner, open_workday, menu, owner_conn):
    p = menu["Sunset Passion"]
    r = await post_sale(
        owner,
        [
            line(p, 2, "Matcha", "Yogurt griego"),
            line(p, 1, "Avena", "Chai pistacho"),
            line(menu["Passion Soda"], 1),
        ],
    )
    assert r.status_code == 201, r.text
    sale = r.json()
    first, second, soda = sale["items"]
    # Options come back in group order, whatever the order sent.
    assert first["options"] == [
        {"group_name": "Base", "option_name": "Yogurt griego", "price_delta_cop": 0},
        {"group_name": "Té", "option_name": "Matcha", "price_delta_cop": 0},
    ]
    assert first["unit_price_cop"] == 14000
    # R3: the option price is added by the backend.
    assert second["unit_price_cop"] == 15000
    assert soda["options"] == []
    assert sale["total_cop"] == 2 * 14000 + 15000 + 12000
    assert (
        owner_conn.execute("SELECT count(*) FROM sale_item_option").fetchone()[0] == 4
    )

    # The copies survive later changes to the configuration.
    owner_conn.execute(
        "UPDATE option_choice SET name = 'Avena light' WHERE name = 'Avena'"
    )
    owner_conn.commit()
    again = (await owner.get(f"/api/op/sales/{sale['id']}")).json()
    assert again["items"][1]["options"][0]["option_name"] == "Avena"


@pytest.fixture
def all_choices(menu, owner_conn) -> dict[str, str]:
    """Every choice id by name, including those the API never shows."""
    return {
        name: str(choice_id)
        for name, choice_id in owner_conn.execute(
            "SELECT name, id FROM option_choice"
        ).fetchall()
    }


@pytest.mark.parametrize(
    "names",
    [
        (),  # required groups missing
        ("Yogurt griego",),  # Té missing
        ("Yogurt griego", "Avena", "Matcha"),  # two bases, max 1
        ("Yogurt griego", "Matcha", "Chía"),  # group not linked to the product
        ("Coco", "Matcha"),  # inactive choice
    ],
)
async def test_invalid_options(owner, open_workday, menu, all_choices, names):
    p = menu["Sunset Passion"]
    r = await post_sale(
        owner,
        [
            {
                "product_id": p["id"],
                "qty": 1,
                "option_ids": [all_choices[n] for n in names],
            }
        ],
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "options_invalid"


async def test_options_on_product_without_groups(owner, open_workday, menu):
    soda = menu["Passion Soda"]
    r = await post_sale(
        owner,
        [
            {
                "product_id": soda["id"],
                "qty": 1,
                "option_ids": [option_ids(menu["Sunset Passion"])["Matcha"]],
            }
        ],
    )
    assert r.json()["error"]["code"] == "options_invalid"


async def test_optional_multi_choice_group(owner, open_workday, menu):
    """Generic min/max: 0 to 2 toppings on a product."""
    data = seed_data()
    soda_row = next(p for p in data["products"] if p["name"] == "Passion Soda")
    soda_row["option_groups"] = ["Toppings"]
    seed(OWNER_URL, data)
    products = (await owner.get("/api/op/products")).json()
    soda = next(p for p in products if p["name"] == "Passion Soda")
    ids = option_ids(soda)

    async def sell_soda(*names):
        return await post_sale(
            owner,
            [
                {
                    "product_id": soda["id"],
                    "qty": 1,
                    "option_ids": [ids[n] for n in names],
                }
            ],
        )

    assert (await sell_soda()).status_code == 201
    assert (await sell_soda("Chía", "Granola")).status_code == 201
    r = await sell_soda("Chía", "Chía")
    assert r.json()["error"]["code"] == "options_invalid"


async def test_same_product_and_options_twice_is_rejected(owner, open_workday, menu):
    p = menu["Sunset Passion"]
    r = await post_sale(
        owner,
        [line(p, 1, "Avena", "Matcha"), line(p, 1, "Matcha", "Avena")],
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_percent_prize_goes_to_most_expensive_line(
    owner, open_workday, menu, seeded, owner_conn, customer_client, rng
):
    customer_id, award_id, _ = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "50% de descuento"
    )
    p = menu["Sunset Passion"]
    r = await post_sale(
        owner,
        [line(p, 1, "Yogurt griego", "Matcha"), line(p, 1, "Avena", "Matcha")],
        customer_id=customer_id,
        prize_award_id=award_id,
        prize_target_product_id=p["id"],
    )
    assert r.status_code == 201, r.text
    cheap, dear = r.json()["items"]
    assert cheap["discount_cop"] == 0
    assert dear["discount_cop"] == 7500  # 50% of 15000
    assert dear["prize_award_id"] == award_id


async def test_free_item_on_paid_sale_with_options(
    owner, open_workday, menu, seeded, owner_conn, customer_client, rng
):
    _, award_id, sale_id = await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "Bebida gratis"
    )
    p = menu["Sunset Passion"]
    url = f"/api/op/sales/{sale_id}/redeem-prize"
    r = await owner.post(url, json={"prize_award_id": award_id, "product_id": p["id"]})
    assert r.json()["error"]["code"] == "options_invalid"
    ids = option_ids(p)
    r = await owner.post(
        url,
        json={
            "prize_award_id": award_id,
            "product_id": p["id"],
            "option_ids": [ids["Yogurt griego"], ids["Chai pistacho"]],
        },
    )
    assert r.status_code == 200, r.text
    free = r.json()["items"][1]
    assert [o["option_name"] for o in free["options"]] == [
        "Yogurt griego",
        "Chai pistacho",
    ]
    assert free["unit_price_cop"] == free["discount_cop"] == 14000


async def test_options_in_lists_history_and_csv(
    owner, open_workday, menu, owner_conn, customer_client
):
    p = menu["Sunset Passion"]
    sale = (await post_sale(owner, [line(p, 1, "Avena", "Matcha")])).json()
    await register(customer_client, claim_token(owner_conn, sale["id"]))

    sales = (await owner.get(f"/api/op/workdays/{open_workday['id']}/sales")).json()
    assert [o["option_name"] for o in sales["items"][0]["items"][0]["options"]] == [
        "Avena",
        "Matcha",
    ]

    history = (await customer_client.get("/api/c/history")).json()
    assert [o["option_name"] for o in history[0]["items"][0]["options"]] == [
        "Avena",
        "Matcha",
    ]

    today = local_today("America/Bogota").isoformat()
    r = await owner.get(f"/api/op/export/sales.csv?from={today}&to={today}")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows[0]["options"] == "Base: Avena; Té: Matcha"


async def test_seed_is_idempotent_and_unlinks(owner, seeded, owner_conn):
    created = seed(OWNER_URL, seed_data())
    assert created["option_group"] == 3
    assert seed(OWNER_URL, seed_data()) == {
        "business": 0,
        "category": 0,
        "option_group": 0,
        "product": 0,
        "prize_catalog": 0,
    }
    # Removing a group from the product's list unlinks it (no delete, R19).
    data = seed_data()
    data["products"][-1]["option_groups"] = ["Base"]
    seed(OWNER_URL, data)
    p = next(
        x
        for x in (await owner.get("/api/op/products")).json()
        if x["name"] == "Sunset Passion"
    )
    assert [g["name"] for g in p["option_groups"]] == ["Base"]
    assert (
        owner_conn.execute("SELECT count(*) FROM product_option_group").fetchone()[0]
        == 2
    )
    # Retiring a product hides it from the sale screen; its rows stay.
    data["products"][1]["active"] = False
    seed(OWNER_URL, data)
    names = [x["name"] for x in (await owner.get("/api/op/products")).json()]
    assert "Green Chai Latte" not in names


async def test_unknown_group_in_seed_fails(seeded):
    data = seed_data()
    data["products"][-1]["option_groups"] = ["Nope"]
    with pytest.raises(SystemExit):
        seed(OWNER_URL, data)


async def test_sell_helper_still_works_without_options(owner, open_workday, seeded):
    r = await sell(owner, [(seeded.products["Passion Soda"], 1)])
    assert r.status_code == 201


async def test_option_sales_in_workday_stats(owner, open_workday, menu):
    p = menu["Sunset Passion"]
    await post_sale(
        owner, [line(p, 2, "Avena", "Matcha"), line(p, 1, "Avena", "Chai pistacho")]
    )
    voided = (await post_sale(owner, [line(p, 5, "Yogurt griego", "Matcha")])).json()
    await owner.post(f"/api/op/sales/{voided['id']}/void", json={"reason": "error"})

    stats = (await owner.get(f"/api/op/stats/workdays/{open_workday['id']}")).json()
    rows = [(o["group_name"], o["option_name"], o["units"]) for o in stats["options"]]
    # Void sales don't count; most units first.
    assert rows == [
        ("Base", "Avena", 3),
        ("Té", "Matcha", 2),
        ("Té", "Chai pistacho", 1),
    ]
    assert {o["category"] for o in stats["options"]} == {None}
