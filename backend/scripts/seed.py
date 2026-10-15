"""Idempotent seed: business, option groups, products and prize catalog from seed_data.json.

Looks up rows by business.slug, option_group.name, option_choice.name, product.name
and prize_catalog.name; inserts or updates. Nothing is deleted (R19): to retire a
product, option group or choice, keep it in the file with "active": false. A
product's "option_groups" list is complete: groups no longer listed are unlinked.
To rename a product, set "name" to the new name and "renamed_from" to the old one:
the same row (and its sales history) is kept. Products may name a "category"
(a section of the sale screen) and turn off "earns_stamp" or "prize_eligible".
Connects with MIGRATION_DATABASE_URL:

    uv run --env-file .env python scripts/seed.py
"""

import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

DATA_FILE = Path(__file__).with_name("seed_data.json")


def upsert_business(conn: psycopg.Connection, b: dict) -> tuple[str, bool]:
    row = conn.execute(
        "SELECT id FROM business WHERE slug = %s FOR UPDATE", (b["slug"],)
    ).fetchone()
    values = (
        b["name"],
        b["timezone"],
        b["latitude"],
        b["longitude"],
        Jsonb(b["branding"]),
        b["milestone_every"],
    )
    if row:
        conn.execute(
            "UPDATE business SET name = %s, timezone = %s, latitude = %s, longitude = %s, "
            "branding = %s, milestone_every = %s WHERE id = %s",
            (*values, row[0]),
        )
        return row[0], False
    row = conn.execute(
        "INSERT INTO business (name, timezone, latitude, longitude, branding, "
        "milestone_every, slug) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (*values, b["slug"]),
    ).fetchone()
    return row[0], True


def upsert_option_group(conn: psycopg.Connection, business_id, g: dict) -> tuple:
    """Returns (group id, created)."""
    row = conn.execute(
        "SELECT id FROM option_group WHERE business_id = %s AND name = %s FOR UPDATE",
        (business_id, g["name"]),
    ).fetchone()
    values = (
        g.get("min_select", 1),
        g.get("max_select", 1),
        g.get("sort_order", 0),
        g.get("active", True),
    )
    if row:
        group_id, created = row[0], False
        conn.execute(
            "UPDATE option_group SET min_select = %s, max_select = %s, "
            "sort_order = %s, active = %s WHERE id = %s",
            (*values, group_id),
        )
    else:
        group_id, created = (
            conn.execute(
                "INSERT INTO option_group (min_select, max_select, sort_order, active, "
                "business_id, name) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (*values, business_id, g["name"]),
            ).fetchone()[0],
            True,
        )
    for c in g.get("options", []):
        values = (
            c.get("price_delta_cop", 0),
            c.get("sort_order", 0),
            c.get("active", True),
        )
        updated = conn.execute(
            "UPDATE option_choice SET price_delta_cop = %s, sort_order = %s, "
            "active = %s WHERE group_id = %s AND name = %s",
            (*values, group_id, c["name"]),
        )
        if updated.rowcount == 0:
            conn.execute(
                "INSERT INTO option_choice (price_delta_cop, sort_order, active, "
                "group_id, name) VALUES (%s, %s, %s, %s, %s)",
                (*values, group_id, c["name"]),
            )
    return group_id, created


def upsert_category(conn: psycopg.Connection, business_id, c: dict) -> tuple:
    """Returns (category id, created)."""
    values = (c.get("sort_order", 0), c.get("active", True))
    row = conn.execute(
        "UPDATE product_category SET sort_order = %s, active = %s "
        "WHERE business_id = %s AND name = %s RETURNING id",
        (*values, business_id, c["name"]),
    ).fetchone()
    if row:
        return row[0], False
    row = conn.execute(
        "INSERT INTO product_category (sort_order, active, business_id, name) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (*values, business_id, c["name"]),
    ).fetchone()
    return row[0], True


def find_product(conn: psycopg.Connection, business_id, name: str):
    return conn.execute(
        "SELECT id FROM product WHERE business_id = %s AND name = %s FOR UPDATE",
        (business_id, name),
    ).fetchone()


def upsert_product(
    conn: psycopg.Connection,
    business_id,
    p: dict,
    groups: dict[str, object],
    categories: dict[str, object],
) -> bool:
    category = p.get("category")
    if category is not None and category not in categories:
        raise SystemExit(f"Product {p['name']!r}: unknown category {category!r}")
    row = find_product(conn, business_id, p["name"])
    if row is None and p.get("renamed_from"):
        row = find_product(conn, business_id, p["renamed_from"])
    values = (
        p["price_cop"],
        p["cost_cop"],
        p["sort_order"],
        p.get("description"),
        p.get("photo_url"),
        categories.get(category),
        p.get("earns_stamp", True),
        p.get("prize_eligible", True),
        p.get("active", True),
        p["name"],
    )
    if row:
        product_id, created = row[0], False
        conn.execute(
            "UPDATE product SET price_cop = %s, cost_cop = %s, sort_order = %s, "
            "description = %s, photo_url = %s, category_id = %s, earns_stamp = %s, "
            "prize_eligible = %s, active = %s, name = %s WHERE id = %s",
            (*values, product_id),
        )
    else:
        product_id, created = (
            conn.execute(
                "INSERT INTO product (price_cop, cost_cop, sort_order, description, "
                "photo_url, category_id, earns_stamp, prize_eligible, active, name, "
                "business_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id",
                (*values, business_id),
            ).fetchone()[0],
            True,
        )
    # The list is complete: unlink every group, then (re)link the listed ones.
    conn.execute(
        "UPDATE product_option_group SET active = false WHERE product_id = %s",
        (product_id,),
    )
    for order, name in enumerate(p.get("option_groups", []), start=1):
        if name not in groups:
            raise SystemExit(f"Product {p['name']!r}: unknown option group {name!r}")
        conn.execute(
            "INSERT INTO product_option_group (product_id, group_id, sort_order) "
            "VALUES (%s, %s, %s) ON CONFLICT (product_id, group_id) "
            "DO UPDATE SET sort_order = EXCLUDED.sort_order, active = true",
            (product_id, groups[name], order),
        )
    return created


def upsert_prize(conn: psycopg.Connection, business_id, p: dict) -> bool:
    row = conn.execute(
        "SELECT id FROM prize_catalog WHERE business_id = %s AND name = %s FOR UPDATE",
        (business_id, p["name"]),
    ).fetchone()
    values = (
        p["short_label"],
        p["type"],
        p["value"],
        p["max_value_cop"],
        p["weight"],
        p["expires_days"],
        p["color"],
        p["sort_order"],
    )
    if row:
        conn.execute(
            "UPDATE prize_catalog SET short_label = %s, type = %s, value = %s, "
            "max_value_cop = %s, weight = %s, expires_days = %s, color = %s, "
            "sort_order = %s WHERE id = %s",
            (*values, row[0]),
        )
        return False
    conn.execute(
        "INSERT INTO prize_catalog (short_label, type, value, max_value_cop, weight, "
        "expires_days, color, sort_order, business_id, name) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (*values, business_id, p["name"]),
    )
    return True


def seed(url: str, data: dict) -> dict[str, int]:
    """Runs everything in one transaction. Returns how many rows were created."""
    created = {
        "business": 0,
        "category": 0,
        "option_group": 0,
        "product": 0,
        "prize_catalog": 0,
    }
    with psycopg.connect(url) as conn, conn.transaction():
        business_id, is_new = upsert_business(conn, data["business"])
        created["business"] += is_new
        categories = {}
        for c in data.get("categories", []):
            categories[c["name"]], is_new = upsert_category(conn, business_id, c)
            created["category"] += is_new
        groups = {}
        for g in data.get("option_groups", []):
            groups[g["name"]], is_new = upsert_option_group(conn, business_id, g)
            created["option_group"] += is_new
        for p in data["products"]:
            created["product"] += upsert_product(
                conn, business_id, p, groups, categories
            )
        for p in data["prize_catalog"]:
            created["prize_catalog"] += upsert_prize(conn, business_id, p)
    return created


def main() -> None:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        sys.exit("MIGRATION_DATABASE_URL is not set")
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    created = seed(url, data)
    print("Seed done. Rows created:", created)


if __name__ == "__main__":
    main()
