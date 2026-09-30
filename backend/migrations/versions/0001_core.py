"""core schema

Revision ID: 0001_core
Revises:
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(r"""
-- ============ business ============
CREATE TABLE business (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug             text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]{2,40}$'),
  name             text NOT NULL,
  timezone         text NOT NULL DEFAULT 'America/Bogota',
  latitude         numeric(8,5),
  longitude        numeric(8,5),
  branding         jsonb NOT NULL DEFAULT '{}'::jsonb,
  milestone_every  smallint NOT NULL DEFAULT 5 CHECK (milestone_every BETWEEN 2 AND 50),
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- ============ operator ============
CREATE TABLE operator (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id    uuid NOT NULL REFERENCES business(id),
  email          text NOT NULL UNIQUE CHECK (email = lower(email)),
  name           text NOT NULL,
  password_hash  text NOT NULL,
  role           text NOT NULL CHECK (role IN ('owner','operator')),
  active         boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE operator_session (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id  uuid NOT NULL REFERENCES operator(id),
  token_hash   text NOT NULL UNIQUE,
  user_agent   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  revoked_at   timestamptz
);
CREATE INDEX operator_session_operator ON operator_session (operator_id);

-- ============ product ============
CREATE TABLE product (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id  uuid NOT NULL REFERENCES business(id),
  name         text NOT NULL,
  price_cop    integer NOT NULL CHECK (price_cop > 0),
  cost_cop     integer CHECK (cost_cop IS NULL OR cost_cop >= 0),
  photo_url    text,
  sort_order   integer NOT NULL DEFAULT 0,
  active       boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, name)
);

-- ============ workday (jornada) ============
CREATE TABLE workday (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id     uuid NOT NULL REFERENCES business(id),
  local_date      date NOT NULL,
  day_type        text NOT NULL CHECK (day_type IN ('sunday','holiday','other')),
  status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  opened_at       timestamptz NOT NULL DEFAULT now(),
  opened_by       uuid NOT NULL REFERENCES operator(id),
  closed_at       timestamptz,
  closed_by       uuid REFERENCES operator(id),
  weather_temp_c  numeric(4,1),
  weather_code    smallint,
  UNIQUE (business_id, local_date),
  CHECK ((status = 'closed') = (closed_at IS NOT NULL AND closed_by IS NOT NULL))
);
CREATE UNIQUE INDEX workday_one_open ON workday (business_id) WHERE status = 'open';

-- ============ customer ============
CREATE TABLE customer (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id      uuid NOT NULL REFERENCES business(id),
  phone            text NOT NULL CHECK (phone ~ '^\+573[0-9]{9}$'),
  alias            text NOT NULL CHECK (char_length(alias) BETWEEN 2 AND 30),
  consent_at       timestamptz NOT NULL,
  consent_version  text NOT NULL,
  referred_by      uuid REFERENCES customer(id),   -- reservado para referidos (V2). No usar.
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, phone)
);
CREATE INDEX customer_last4 ON customer (business_id, right(phone, 4));

CREATE TABLE customer_session (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id  uuid NOT NULL REFERENCES customer(id),
  token_hash   text NOT NULL UNIQUE,
  user_agent   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  revoked_at   timestamptz
);
CREATE INDEX customer_session_customer ON customer_session (customer_id);

-- ============ sale ============
CREATE TABLE sale (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id       uuid NOT NULL REFERENCES business(id),
  workday_id        uuid NOT NULL REFERENCES workday(id),
  operator_id       uuid NOT NULL REFERENCES operator(id),
  customer_id       uuid REFERENCES customer(id),
  status            text NOT NULL CHECK (status IN ('paid','claimed','void')),
  payment_method    text NOT NULL CHECK (payment_method IN ('cash','nequi','breb','card')),
  total_cop         integer NOT NULL CHECK (total_cop >= 0),
  idempotency_key   uuid NOT NULL UNIQUE,
  claim_token       text NOT NULL UNIQUE,
  claim_expires_at  timestamptz NOT NULL,
  claim_method      text CHECK (claim_method IN ('qr','manual')),
  paid_at           timestamptz NOT NULL DEFAULT now(),
  claimed_at        timestamptz,
  voided_at         timestamptz,
  voided_by         uuid REFERENCES operator(id),
  void_reason       text,
  CHECK (status <> 'paid'    OR (customer_id IS NULL AND claimed_at IS NULL AND claim_method IS NULL)),
  CHECK (status <> 'claimed' OR (customer_id IS NOT NULL AND claimed_at IS NOT NULL AND claim_method IS NOT NULL)),
  CHECK (status <> 'void'    OR (voided_at IS NOT NULL AND voided_by IS NOT NULL AND void_reason IS NOT NULL))
);
CREATE INDEX sale_workday  ON sale (business_id, workday_id);
CREATE INDEX sale_customer ON sale (customer_id, workday_id);
CREATE INDEX sale_paid_at  ON sale (business_id, paid_at);

-- ============ prize_catalog ============
CREATE TABLE prize_catalog (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id    uuid NOT NULL REFERENCES business(id),
  name           text NOT NULL,
  short_label    text NOT NULL CHECK (char_length(short_label) <= 14),
  type           text NOT NULL CHECK (type IN ('percent_off','free_item','extra_item')),
  value          integer NOT NULL DEFAULT 0,
  max_value_cop  integer CHECK (max_value_cop IS NULL OR max_value_cop > 0),
  weight         integer NOT NULL CHECK (weight > 0),
  expires_days   smallint NOT NULL DEFAULT 90 CHECK (expires_days > 0),
  color          text,
  sort_order     integer NOT NULL DEFAULT 0,
  active         boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CHECK (type <> 'percent_off' OR value BETWEEN 1 AND 100)
);

-- ============ spin ============
CREATE TABLE spin (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id          uuid NOT NULL REFERENCES business(id),
  customer_id          uuid NOT NULL REFERENCES customer(id),
  reason               text NOT NULL CHECK (reason IN ('welcome','milestone')),
  milestone_n          integer,
  unlocked_by_sale_id  uuid NOT NULL REFERENCES sale(id),
  status               text NOT NULL DEFAULT 'available' CHECK (status IN ('available','consumed','void')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  spun_at              timestamptz,
  voided_at            timestamptz,
  CHECK ((reason = 'milestone') = (milestone_n IS NOT NULL)),
  CHECK (status <> 'consumed' OR spun_at IS NOT NULL),
  CHECK (status <> 'void' OR voided_at IS NOT NULL)
);
-- R9: un solo giro de bienvenida vigente por cliente
CREATE UNIQUE INDEX spin_one_welcome   ON spin (customer_id) WHERE reason = 'welcome' AND status <> 'void';
-- R10: un solo giro vigente por hito
CREATE UNIQUE INDEX spin_one_milestone ON spin (customer_id, milestone_n) WHERE reason = 'milestone' AND status <> 'void';
CREATE INDEX spin_sale ON spin (unlocked_by_sale_id);

-- ============ prize_award ============
CREATE TABLE prize_award (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id       uuid NOT NULL REFERENCES business(id),
  customer_id       uuid NOT NULL REFERENCES customer(id),
  spin_id           uuid NOT NULL UNIQUE REFERENCES spin(id),
  prize_id          uuid NOT NULL REFERENCES prize_catalog(id),
  status            text NOT NULL DEFAULT 'active' CHECK (status IN ('active','redeemed','void')),
  awarded_at        timestamptz NOT NULL DEFAULT now(),
  expires_at        timestamptz NOT NULL,
  redeemed_at       timestamptz,
  redeemed_sale_id  uuid REFERENCES sale(id),
  redeemed_by       uuid REFERENCES operator(id),
  voided_at         timestamptz,
  CHECK ((status = 'redeemed') = (redeemed_at IS NOT NULL AND redeemed_sale_id IS NOT NULL AND redeemed_by IS NOT NULL)),
  CHECK (status <> 'void' OR voided_at IS NOT NULL)
);
-- R16: máximo un premio redimido por venta
CREATE UNIQUE INDEX prize_one_per_sale ON prize_award (redeemed_sale_id) WHERE status = 'redeemed';
CREATE INDEX prize_award_customer ON prize_award (customer_id, status);
CREATE INDEX prize_award_expiry   ON prize_award (business_id, expires_at) WHERE status = 'active';

-- ============ sale_item ============
CREATE TABLE sale_item (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sale_id         uuid NOT NULL REFERENCES sale(id),
  product_id      uuid REFERENCES product(id),
  label           text NOT NULL,                 -- copia del nombre al vender
  qty             integer NOT NULL CHECK (qty > 0),
  unit_price_cop  integer NOT NULL CHECK (unit_price_cop >= 0),
  unit_cost_cop   integer CHECK (unit_cost_cop IS NULL OR unit_cost_cop >= 0),
  discount_cop    integer NOT NULL DEFAULT 0 CHECK (discount_cop >= 0),
  prize_award_id  uuid REFERENCES prize_award(id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (product_id IS NOT NULL OR prize_award_id IS NOT NULL),
  CHECK (discount_cop <= unit_price_cop * qty)
);
CREATE INDEX sale_item_sale    ON sale_item (sale_id);
CREATE INDEX sale_item_product ON sale_item (product_id);

-- ============ event ============
CREATE TABLE event (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id  uuid NOT NULL REFERENCES business(id),
  type         text NOT NULL,
  actor        text NOT NULL CHECK (actor IN ('customer','operator','system')),
  actor_id     uuid,
  customer_id  uuid,
  sale_id      uuid,
  workday_id   uuid,
  payload      jsonb NOT NULL DEFAULT '{}'::jsonb,
  client_ts    timestamptz,
  server_ts    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX event_type     ON event (business_id, type, server_ts);
CREATE INDEX event_sale     ON event (sale_id);
CREATE INDEX event_customer ON event (customer_id);
""")


def downgrade() -> None:
    op.execute(r"""
DROP TABLE event;
DROP TABLE sale_item;
DROP TABLE prize_award;
DROP TABLE spin;
DROP TABLE prize_catalog;
DROP TABLE sale;
DROP TABLE customer_session;
DROP TABLE customer;
DROP TABLE workday;
DROP TABLE product;
DROP TABLE operator_session;
DROP TABLE operator;
DROP TABLE business;
""")
