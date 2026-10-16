"""Wheel editor: PUT /api/admin/prizes/catalog (owner only)."""

import json

from scripts.seed import seed
from tests.api.conftest import OWNER_URL, TEST_DATA, customer_with_prize

URL = "/api/admin/prizes/catalog"
EDITABLE = (
    "id",
    "name",
    "short_label",
    "type",
    "value",
    "max_value_cop",
    "weight",
    "expires_days",
    "color",
    "active",
)


async def wheel(owner) -> list[dict]:
    """The catalog as editor rows (seed weights 40/25/20/10/5 -> hundredths of %)."""
    rows = (await owner.get(URL)).json()
    return [{k: p[k] for k in EDITABLE} | {"weight": p["weight"] * 100} for p in rows]


def by_name(rows: list[dict]) -> dict[str, dict]:
    return {r["name"]: r for r in rows}


async def test_operator_cannot_edit(owner, operator):
    rows = await wheel(owner)
    r = await operator.put(URL, json={"prizes": rows})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


async def test_save_wheel_round_trip(owner, owner_conn):
    rows = await wheel(owner)
    p = by_name(rows)
    p["10% de descuento"]["weight"] = 3750  # 37.5 %
    p["Cold foam o topping extra"]["weight"] = 2750
    p["Bebida gratis"]["short_label"] = "Gratis!"
    new = {
        "name": "Galleta gratis",
        "short_label": "Galleta",
        "type": "extra_item",
        "value": 0,
        "max_value_cop": 9000,  # dropped: extra items are never capped
        "weight": 1,
        "expires_days": 30,
        "color": "#5DA882",
        "active": False,
    }
    # New order: the new prize first, the rest reversed.
    body = {"prizes": [new, *reversed(rows)]}
    r = await owner.put(URL, json=body)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert [s["name"] for s in saved] == [
        new["name"],
        *[x["name"] for x in reversed(rows)],
    ]
    assert [s["sort_order"] for s in saved] == [1, 2, 3, 4, 5, 6]
    s = by_name(saved)
    assert s["10% de descuento"]["weight"] == 3750
    assert s["Bebida gratis"]["short_label"] == "Gratis!"
    assert s["Galleta gratis"]["max_value_cop"] is None
    assert s["Galleta gratis"]["active"] is False
    assert all(x["awarded"] is False for x in saved)
    assert (await owner.get(URL)).json() == saved

    # The customer wheel follows: active prizes only, in the new order.
    wheel_out = (await owner.get("/api/client/wheel")).json()["segments"]
    assert [w["short_label"] for w in wheel_out] == [
        x["short_label"] for x in saved if x["active"]
    ]

    # Audited with the before and after catalog.
    payload = owner_conn.execute(
        "SELECT payload FROM event WHERE type = 'prize_catalog_updated'"
    ).fetchone()[0]
    assert {p["name"] for p in payload["before"]} == {x["name"] for x in rows}
    assert len(payload["after"]) == 6


async def test_active_weights_must_total_100(owner):
    rows = await wheel(owner)
    rows[0]["weight"] += 1
    r = await owner.put(URL, json={"prizes": rows})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "wheel_total_invalid"
    # Inactive prizes don't count toward the 100 %.
    rows[0]["weight"] -= 1
    rows.append(rows.pop() | {"active": False, "weight": 999})
    by_name(rows)["10% de descuento"]["weight"] += 500  # the 5 % of "Bebida gratis"
    r = await owner.put(URL, json={"prizes": rows})
    assert r.status_code == 200, r.text


async def test_needs_two_to_twelve_active_prizes(owner):
    rows = await wheel(owner)
    for r in rows[1:]:
        r["active"] = False
    rows[0]["weight"] = 10_000
    r = await owner.put(URL, json={"prizes": rows})
    assert r.json()["error"]["code"] == "wheel_size_invalid"


async def test_every_existing_prize_must_be_listed(owner):
    rows = await wheel(owner)
    r = await owner.put(URL, json={"prizes": rows[1:]})
    assert r.json()["error"]["code"] == "validation_error"
    r = await owner.put(URL, json={"prizes": [*rows, rows[0]]})
    assert r.json()["error"]["code"] == "validation_error"


async def test_names_are_unique(owner):
    rows = await wheel(owner)
    rows[1]["name"] = rows[0]["name"].upper()
    r = await owner.put(URL, json={"prizes": rows})
    assert r.json()["error"]["code"] == "prize_name_taken"


async def test_invalid_rows(owner):
    rows = await wheel(owner)
    for bad in (
        {"type": "percent_off", "value": 0},
        {"short_label": "x" * 15},
        {"color": "red"},
        {"weight": 0},
        {"expires_days": 0},
    ):
        body = {"prizes": [rows[0] | bad, *rows[1:]]}
        r = await owner.put(URL, json=body)
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "validation_error", bad


async def test_won_prize_keeps_its_reward(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "10% de descuento"
    )
    rows = await wheel(owner)
    assert {r["name"]: r for r in (await owner.get(URL)).json()}["10% de descuento"][
        "awarded"
    ]

    for change in ({"value": 15}, {"type": "free_item"}, {"max_value_cop": 9000}):
        body = [r | change if r["name"] == "10% de descuento" else r for r in rows]
        r = await owner.put(URL, json={"prizes": body})
        assert r.status_code == 409, change
        assert r.json()["error"]["code"] == "prize_locked"

    # Name, label, chance, expiry and active can still change; the award is untouched.
    p = by_name(rows)["10% de descuento"]
    p |= {"name": "10% off", "short_label": "10%", "expires_days": 10, "active": False}
    by_name(rows)["20% de descuento"]["weight"] += p["weight"]
    r = await owner.put(URL, json={"prizes": rows})
    assert r.status_code == 200, r.text
    card = (await customer_client.get("/api/client/me")).json()
    assert card["active_prizes"][0]["name"] == "10% off"


async def test_seed_rerun_keeps_owner_edits(owner):
    rows = await wheel(owner)
    by_name(rows)["Bebida gratis"]["short_label"] = "Gratis!"
    assert (await owner.put(URL, json={"prizes": rows})).status_code == 200
    created = seed(OWNER_URL, json.loads(json.dumps(TEST_DATA)))
    assert created["prize_catalog"] == 0
    saved = by_name((await owner.get(URL)).json())
    assert saved["Bebida gratis"]["short_label"] == "Gratis!"


def category_id(conn, business_id, name) -> str:
    row = conn.execute(
        "INSERT INTO product_category (business_id, name) VALUES (%s, %s) "
        "ON CONFLICT (business_id, name) DO UPDATE SET name = EXCLUDED.name "
        "RETURNING id",
        (business_id, name),
    ).fetchone()
    conn.commit()
    return str(row[0])


async def test_prize_category_round_trip(owner, owner_conn, seeded):
    helados = category_id(owner_conn, seeded.business_id, "Helados")
    rows = await wheel(owner)
    by_name(rows)["Bebida gratis"]["category_id"] = helados
    r = await owner.put(URL, json={"prizes": rows})
    assert r.status_code == 200, r.text
    saved = by_name(r.json())
    assert saved["Bebida gratis"]["category_id"] == helados
    assert saved["10% de descuento"]["category_id"] is None


async def test_prize_category_of_another_business(owner, owner_conn):
    other = owner_conn.execute(
        "INSERT INTO business (slug, name, timezone) "
        "VALUES ('other', 'Other', 'America/Bogota') RETURNING id"
    ).fetchone()[0]
    owner_conn.commit()
    rows = await wheel(owner)
    rows[0]["category_id"] = category_id(owner_conn, other, "Helados")
    r = await owner.put(URL, json={"prizes": rows})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_won_prize_keeps_its_category(
    owner, open_workday, seeded, owner_conn, customer_client, rng
):
    await customer_with_prize(
        owner, seeded, owner_conn, customer_client, rng, "10% de descuento"
    )
    helados = category_id(owner_conn, seeded.business_id, "Helados")
    rows = await wheel(owner)
    by_name(rows)["10% de descuento"]["category_id"] = helados
    r = await owner.put(URL, json={"prizes": rows})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "prize_locked"
