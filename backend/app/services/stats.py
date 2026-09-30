"""Operator statistics (11.12), from the reporting views."""

import csv
import io
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError


async def workday_summary(
    db: AsyncSession, business_id: UUID, workday_id: UUID
) -> dict | None:
    """One row of v_workday_summary (R21: filtered by business)."""
    row = (
        (
            await db.execute(
                text(
                    "SELECT * FROM v_workday_summary "
                    "WHERE business_id = :business_id AND workday_id = :workday_id"
                ),
                {"business_id": business_id, "workday_id": workday_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def with_rates(summary: dict) -> dict:
    sales = summary["sales"]
    return {
        **summary,
        "drinks_per_sale": round(summary["drinks"] / sales, 2) if sales else 0,
        "claimed_pct": summary["claimed_sales"] / sales if sales else 0,
    }


def product_ranking(rows: list[dict]) -> list[dict]:
    """Aggregate v_product_sales rows by product, most units first.

    If a product has no cost, cost_incomplete is true and no margin is shown.
    """
    by_product: dict[UUID, dict] = {}
    for r in rows:
        p = by_product.setdefault(
            r["product_id"],
            {
                "product_id": r["product_id"],
                "label": r["label"],
                "units": 0,
                "gross_cop": 0,
                "discount_cop": 0,
                "net_cop": 0,
                "cost_cop": 0,
                "cost_incomplete": False,
            },
        )
        for key in ("units", "gross_cop", "discount_cop", "net_cop", "cost_cop"):
            p[key] += int(r[key])
        p["cost_incomplete"] = p["cost_incomplete"] or r["cost_incomplete"]
    ranking = sorted(by_product.values(), key=lambda p: (-p["units"], p["label"]))
    for p in ranking:
        p["margin_cop"] = None if p["cost_incomplete"] else p["net_cop"] - p["cost_cop"]
    return ranking


def margin(ranking: list[dict]) -> tuple[bool, int | None]:
    incomplete = any(p["cost_incomplete"] for p in ranking)
    if incomplete:
        return True, None
    return False, sum(p["net_cop"] - p["cost_cop"] for p in ranking)


async def workday_stats(db: AsyncSession, business_id: UUID, workday_id: UUID) -> dict:
    summary = await workday_summary(db, business_id, workday_id)
    if summary is None:
        raise AppError("workday_not_found")
    params = {"business_id": business_id, "workday_id": workday_id}
    hourly = [
        dict(r)
        for r in (
            await db.execute(
                text(
                    "SELECT local_hour, sales, revenue_cop FROM v_hourly_sales "
                    "WHERE business_id = :business_id AND workday_id = :workday_id "
                    "ORDER BY local_hour"
                ),
                params,
            )
        ).mappings()
    ]
    products = product_ranking(
        [
            dict(r)
            for r in (
                await db.execute(
                    text(
                        "SELECT * FROM v_product_sales "
                        "WHERE business_id = :business_id AND workday_id = :workday_id"
                    ),
                    params,
                )
            ).mappings()
        ]
    )
    best = max(hourly, key=lambda h: (h["revenue_cop"], -h["local_hour"]), default=None)
    cost_incomplete, margin_cop = margin(products)
    return {
        "summary": with_rates(summary),
        "hourly": hourly,
        "top_products": products[:3],
        "best_hour": best["local_hour"] if best else None,
        "cost_incomplete": cost_incomplete,
        "margin_cop": margin_cop,
    }


async def history_stats(
    db: AsyncSession, business_id: UUID, date_from: date, date_to: date
) -> dict:
    if date_from > date_to:
        raise AppError("validation_error")
    params = {"business_id": business_id, "date_from": date_from, "date_to": date_to}
    workdays = [
        with_rates(dict(r))
        for r in (
            await db.execute(
                text(
                    "SELECT * FROM v_workday_summary WHERE business_id = :business_id "
                    "AND local_date BETWEEN :date_from AND :date_to ORDER BY local_date"
                ),
                params,
            )
        ).mappings()
    ]
    products = product_ranking(
        [
            dict(r)
            for r in (
                await db.execute(
                    text(
                        "SELECT ps.* FROM v_product_sales ps "
                        "JOIN workday w ON w.id = ps.workday_id "
                        "WHERE ps.business_id = :business_id "
                        "AND w.local_date BETWEEN :date_from AND :date_to"
                    ),
                    params,
                )
            ).mappings()
        ]
    )
    totals = (
        await db.execute(
            text(
                "SELECT hs.local_hour, SUM(hs.sales) AS sales, "
                "SUM(hs.revenue_cop) AS revenue_cop FROM v_hourly_sales hs "
                "JOIN workday w ON w.id = hs.workday_id "
                "WHERE hs.business_id = :business_id "
                "AND w.local_date BETWEEN :date_from AND :date_to "
                "GROUP BY hs.local_hour ORDER BY hs.local_hour"
            ),
            params,
        )
    ).mappings()
    # Average per workday in the range (workdays without sales at that hour count as 0).
    n = len(workdays)
    hourly_average = (
        [
            {
                "local_hour": r["local_hour"],
                "avg_sales": round(int(r["sales"]) / n, 2),
                "avg_revenue_cop": round(int(r["revenue_cop"]) / n, 2),
            }
            for r in totals
        ]
        if n
        else []
    )
    cost_incomplete, margin_cop = margin(products)
    return {
        "workdays": workdays,
        "products": products,
        "hourly_average": hourly_average,
        "cost_incomplete": cost_incomplete,
        "margin_cop": margin_cop,
    }


EXPORT_COLUMNS = [
    "sale_id",
    "local_date",
    "paid_at",
    "status",
    "payment_method",
    "sale_total_cop",
    "claim_method",
    "product_id",
    "label",
    "qty",
    "unit_price_cop",
    "unit_cost_cop",
    "discount_cop",
    "net_cop",
    "prize_award_id",
]


async def export_sales_csv(
    db: AsyncSession, business_id: UUID, date_from: date, date_to: date
) -> str:
    """One row per sale line (11.12). Void sales are included, with their status."""
    if date_from > date_to:
        raise AppError("validation_error")
    rows = (
        await db.execute(
            text(
                "SELECT s.id AS sale_id, w.local_date, s.paid_at, s.status, "
                "s.payment_method, s.total_cop AS sale_total_cop, s.claim_method, "
                "si.product_id, si.label, si.qty, si.unit_price_cop, si.unit_cost_cop, "
                "si.discount_cop, si.unit_price_cop * si.qty - si.discount_cop AS net_cop, "
                "si.prize_award_id "
                "FROM sale s JOIN sale_item si ON si.sale_id = s.id "
                "JOIN workday w ON w.id = s.workday_id "
                "WHERE s.business_id = :business_id "
                "AND w.local_date BETWEEN :date_from AND :date_to "
                "ORDER BY s.paid_at, si.created_at"
            ),
            {"business_id": business_id, "date_from": date_from, "date_to": date_to},
        )
    ).mappings()
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for r in rows:
        writer.writerow(
            {
                k: (
                    v.isoformat()
                    if hasattr(v, "isoformat")
                    else ("" if v is None else v)
                )
                for k, v in r.items()
            }
        )
    return out.getvalue()
