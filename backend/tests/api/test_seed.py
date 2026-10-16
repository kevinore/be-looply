"""scripts/seed.py: product photos and renames."""

import copy

from scripts.seed import seed
from tests.api.conftest import OWNER_URL, TEST_DATA, sell


def with_products(**changes_by_name) -> dict:
    data = copy.deepcopy(TEST_DATA)
    for p in data["products"]:
        p.update(changes_by_name.get(p["name"], {}))
    return data


async def test_photo_url(owner, seeded):
    seed(
        OWNER_URL, with_products(**{"Passion Soda": {"photo_url": "/products/x.webp"}})
    )
    products = {p["name"]: p for p in (await owner.get("/api/admin/products")).json()}
    assert products["Passion Soda"]["photo_url"] == "/products/x.webp"
    assert products["Berry Bliss"]["photo_url"] is None


async def test_rename_keeps_the_same_product(owner, open_workday, seeded, owner_conn):
    soda = seeded.products["Passion Soda"]
    sale = (await sell(owner, [(soda, 1)])).json()

    renamed = {"name": "Passion Refresher", "renamed_from": "Passion Soda"}
    data = with_products(**{"Passion Soda": renamed})
    created = seed(OWNER_URL, data)
    assert created["product"] == 0
    # Running it again (new name already there) changes nothing.
    assert seed(OWNER_URL, data)["product"] == 0

    rows = owner_conn.execute(
        "SELECT id, name FROM product WHERE name IN ('Passion Soda', 'Passion Refresher')"
    ).fetchall()
    assert rows == [(soda, "Passion Refresher")]
    # Past sales keep the name they were sold with (sale_item.label is a copy).
    old = (await owner.get(f"/api/admin/sales/{sale['id']}")).json()
    assert old["items"][0]["label"] == "Passion Soda"
    new = (await sell(owner, [(soda, 1)])).json()
    assert new["items"][0]["label"] == "Passion Refresher"
