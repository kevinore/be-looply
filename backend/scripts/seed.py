"""Idempotent seed: business, products and prize catalog from seed_data.json.

Looks up rows by business.slug, product.name and prize_catalog.name; inserts or updates.
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


def upsert_product(conn: psycopg.Connection, business_id, p: dict) -> bool:
    row = conn.execute(
        "SELECT id FROM product WHERE business_id = %s AND name = %s FOR UPDATE",
        (business_id, p["name"]),
    ).fetchone()
    values = (p["price_cop"], p["cost_cop"], p["sort_order"])
    if row:
        conn.execute(
            "UPDATE product SET price_cop = %s, cost_cop = %s, sort_order = %s "
            "WHERE id = %s",
            (*values, row[0]),
        )
        return False
    conn.execute(
        "INSERT INTO product (price_cop, cost_cop, sort_order, business_id, name) "
        "VALUES (%s, %s, %s, %s, %s)",
        (*values, business_id, p["name"]),
    )
    return True


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
    created = {"business": 0, "product": 0, "prize_catalog": 0}
    with psycopg.connect(url) as conn, conn.transaction():
        business_id, is_new = upsert_business(conn, data["business"])
        created["business"] += is_new
        for p in data["products"]:
            created["product"] += upsert_product(conn, business_id, p)
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
