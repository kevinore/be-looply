"""views

Revision ID: 0002_views
Revises: 0001_core
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_views"
down_revision: str | None = "0001_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(r"""
-- R8: compras contabilizadas = jornadas distintas con venta claimed
CREATE VIEW v_customer_purchases AS
SELECT c.id AS customer_id,
       c.business_id,
       COUNT(DISTINCT s.workday_id) FILTER (WHERE s.status = 'claimed') AS purchases
FROM customer c
LEFT JOIN sale s ON s.customer_id = c.id
GROUP BY c.id, c.business_id;

CREATE VIEW v_workday_summary AS
SELECT w.id AS workday_id,
       w.business_id,
       w.local_date,
       w.day_type,
       w.status,
       w.opened_at,
       w.closed_at,
       w.weather_temp_c,
       w.weather_code,
       COUNT(s.id)                                                    AS sales,
       COUNT(s.id) FILTER (WHERE s.status = 'claimed')                AS claimed_sales,
       COALESCE(SUM(s.total_cop), 0)                                  AS revenue_cop,
       COALESCE(SUM(s.total_cop) FILTER (WHERE s.payment_method = 'cash'), 0)  AS cash_cop,
       COALESCE(SUM(s.total_cop) FILTER (WHERE s.payment_method <> 'cash'), 0) AS digital_cop,
       COALESCE(MAX(d.drinks), 0)                                     AS drinks
FROM workday w
LEFT JOIN sale s ON s.workday_id = w.id AND s.status <> 'void'
LEFT JOIN LATERAL (
  SELECT SUM(si.qty) AS drinks
  FROM sale_item si
  JOIN sale s2 ON s2.id = si.sale_id
  WHERE s2.workday_id = w.id AND s2.status <> 'void' AND si.product_id IS NOT NULL
) d ON true
GROUP BY w.id;

CREATE VIEW v_product_sales AS
SELECT s.business_id,
       s.workday_id,
       si.product_id,
       si.label,
       SUM(si.qty)                                   AS units,
       SUM(si.unit_price_cop * si.qty)               AS gross_cop,
       SUM(si.discount_cop)                          AS discount_cop,
       SUM(si.unit_price_cop * si.qty - si.discount_cop) AS net_cop,
       SUM(COALESCE(si.unit_cost_cop, 0) * si.qty)   AS cost_cop,
       BOOL_OR(si.unit_cost_cop IS NULL)             AS cost_incomplete
FROM sale_item si
JOIN sale s ON s.id = si.sale_id
WHERE s.status <> 'void' AND si.product_id IS NOT NULL
GROUP BY s.business_id, s.workday_id, si.product_id, si.label;

CREATE VIEW v_hourly_sales AS
SELECT s.business_id,
       s.workday_id,
       EXTRACT(HOUR FROM s.paid_at AT TIME ZONE b.timezone)::int AS local_hour,
       COUNT(*)           AS sales,
       SUM(s.total_cop)   AS revenue_cop
FROM sale s
JOIN business b ON b.id = s.business_id
WHERE s.status <> 'void'
GROUP BY s.business_id, s.workday_id, local_hour;

CREATE VIEW v_pending_prizes AS
SELECT pa.id AS prize_award_id,
       pa.business_id,
       pa.customer_id,
       c.alias,
       right(c.phone, 4) AS phone_last4,
       pc.name AS prize_name,
       pc.type AS prize_type,
       pa.awarded_at,
       pa.expires_at
FROM prize_award pa
JOIN customer c       ON c.id = pa.customer_id
JOIN prize_catalog pc ON pc.id = pa.prize_id
WHERE pa.status = 'active' AND pa.expires_at > now();
""")


def downgrade() -> None:
    op.execute(r"""
DROP VIEW v_pending_prizes;
DROP VIEW v_hourly_sales;
DROP VIEW v_product_sales;
DROP VIEW v_workday_summary;
DROP VIEW v_customer_purchases;
""")
