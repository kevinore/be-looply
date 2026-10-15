# Plan de ejecución · Base de datos + Backend

> **Proyecto:** PWA de lealtad y ventas para negocios de venta presencial. Primer negocio: **Qué Fresh** (puesto de bebidas saludables, Bogotá, abre domingos y festivos).
> **Nombre de la plataforma:** pendiente. **Nunca** escribas "quefresh" ni "Qué Fresh" en código, nombres de tablas, variables o carpetas. Todo lo propio del negocio vive como **datos** en la tabla `business`.

---

## 0. Instrucciones para Claude Code

1. Ejecuta las fases **en orden**. No empieces una fase sin que la anterior cumpla su sección "Verificación".
2. Los pasos marcados **[HUMANO]** los hace la persona. Detente, explica qué necesitas y espera.
3. **No inventes reglas de negocio.** Si algo no está en este documento, pregunta. Las reglas están numeradas (R1…R21); cita el número en comentarios del código donde las implementes.
4. **Nunca** escribas secretos (contraseñas, cadenas de conexión, tokens) en archivos versionados. Solo en `.env` (ignorado por git) o en los gestores de secretos de Railway y GitHub.
5. Después de cada fase: corre `uv run ruff check .`, `uv run ruff format --check .` y `uv run pytest`. Todo en verde antes de seguir.
6. Commits pequeños, uno por paso, con mensaje descriptivo en inglés.
7. Si un comando falla, lee el error, corrige y reintenta. No desactives restricciones de la base para que algo "pase".

---

## 1. Qué construimos (resumen)

- **App de operador** (`/op`): el operador arma la venta, cobra, muestra un QR único de esa venta, vincula clientes, redime premios y ve estadísticas.
- **App de cliente** (`/c`): el cliente escanea el QR de su compra, se registra con celular + nombre (sin contraseña), acumula compras y gira una ruleta de premios.
- **Sin modo offline.** Todo requiere conexión.
- El backend es la **única** fuente de verdad: calcula precios, descuentos, contadores y premios. El frontend nunca decide nada de eso.

---

## 2. Reglas de negocio (canónicas)

| # | Regla |
|---|---|
| R1 | Solo un operador autenticado crea ventas. El cliente nunca se acredita una compra sin un QR emitido por el operador. |
| R2 | Una venta nace **cobrada** (`paid`). No existe estado "abierta": el carrito vive en el frontend hasta que se toca Cobrar. |
| R3 | Los precios se toman **siempre de la base**. El frontend envía producto y cantidad, nunca precios. El precio y el costo se copian a `sale_item` al vender. |
| R4 | Una venta sin cliente (anónima) es válida y cuenta para estadísticas. |
| R5 | Registrar un cliente o recuperar su identidad **exige un `claim_token` válido y sin reclamar**. Sin compra real, no se puede consultar ni crear clientes (antienumeración). |
| R6 | Cada venta tiene un `claim_token` de **un solo uso**. Una venta se vincula a un solo cliente. |
| R7 | El token vence al **final del día local** o cuando se **cierra la jornada**, lo que ocurra primero. |
| R8 | **Compra contabilizada (sello)** = cada venta `claimed` del cliente suma **un sello**, sin importar cuántos productos tenga ni cuánto tiempo pase desde la anterior. *Decisión del dueño (2026-10-13); antes era 1 sello por jornada. Puede cambiar: la regla vive solo en `app/services/stamps.py` (`STAMP_RULE`), con la regla anterior disponible como `PER_WORKDAY`.* |
| R9 | **Giro de bienvenida:** 1 por cliente, cuando tiene ≥ 1 compra contabilizada. |
| R10 | **Giro de hito:** 1 cada `business.milestone_every` compras (por defecto 5): en la compra 5, 10, 15… Nunca dos giros para el mismo hito. |
| R11 | Los giros disponibles se acumulan y se pueden girar en cualquier momento y lugar. |
| R12 | El **servidor** elige el premio por sorteo ponderado entre premios activos. Los pesos **nunca** salen de la API. Girar dos veces el mismo giro devuelve el mismo premio. |
| R13 | Un premio vence `prize_catalog.expires_days` (por defecto 90) días después de ganarse. |
| R14 | Un premio se puede redimir **desde el momento en que se gana**, incluso en la misma visita. |
| R15 | Solo el **operador** redime premios. El cliente nunca marca un premio como usado. |
| R16 | Máximo **1 premio por venta**. |
| R17 | Todo premio aplica sobre **una unidad de una bebida**. `percent_off` y `free_item` tienen tope `max_value_cop`. |
| R18 | `percent_off` solo se aplica al **crear** una venta (antes de cobrar). `free_item` y `extra_item` pueden aplicarse al crear una venta **o** sobre una venta ya cobrada del mismo cliente, en la jornada abierta, como línea de $0 neto. |
| R19 | **Nada se borra.** Anular marca `void` y dispara cascada (sección 11.8). El rol de la app no tiene permiso `DELETE`. |
| R20 | Toda acción que cambia estado emite un **evento** en la **misma transacción**. Los eventos no se editan ni se borran. |
| R21 | Todo dato pertenece a un `business`. Todas las consultas filtran por el `business_id` del operador o del cliente autenticado. |

---

## 3. Glosario

| Término | Significado |
|---|---|
| `workday` | Jornada: un día de operación del puesto. **No confundir** con sesión de login. |
| `operator_session` / `customer_session` | Sesiones de login. |
| `sale` | Venta cobrada. Estados: `paid` (sin cliente), `claimed` (con cliente), `void` (anulada). |
| `claim` | Acto de vincular una venta a un cliente (por QR o manual). |
| `spin` | Giro de ruleta ganado. Estados: `available`, `consumed`, `void`. |
| `prize_award` | Premio ganado por un cliente. Estados: `active`, `redeemed`, `void`. "Vencido" se calcula (`active` y `expires_at < now()`), no se guarda. |
| Compra contabilizada | Ver R8. |

---

## 4. Stack fijado

| Pieza | Elección |
|---|---|
| Lenguaje | Python 3.12 |
| Dependencias | `uv` |
| Framework | FastAPI + Uvicorn |
| Validación | Pydantic v2 + pydantic-settings |
| ORM | SQLAlchemy 2.x (async) + `asyncpg` |
| Migraciones | Alembic con `psycopg` (síncrono) |
| Contraseñas | `argon2-cffi` |
| Límite de intentos | `slowapi` |
| HTTP saliente | `httpx` |
| Errores | `sentry-sdk[fastapi]` |
| Pruebas | `pytest`, `pytest-asyncio`, `httpx.AsyncClient` |
| Calidad | `ruff` |
| Base de datos | Neon (PostgreSQL 17), ramas `main` y `dev` |
| Hosting | Railway (con Dockerfile) |
| Pruebas locales | PostgreSQL 17 en Docker |

Usa la última versión estable de cada librería.

---

## 5. Fase 0 · Neon: roles y conexiones

### Por qué dos roles (explicación para la persona)

Una base tiene "llaves". Usamos dos:

| Rol | Para qué | Puede | Dónde vive la contraseña |
|---|---|---|---|
| `neondb_owner` (ya existe) | **Construir**: crear y modificar tablas (migraciones) | Todo | Solo en tu computador (`.env`) y en un secreto de GitHub |
| `app_runtime` (nuevo) | **Usar**: la API en Railway | Leer, insertar, actualizar. **No** borrar, **no** crear ni modificar tablas, **no** tocar eventos | En Railway |

Si alguien comprometiera el servidor, con `app_runtime` no podría borrar datos, destruir tablas ni alterar el historial de eventos.

### Pasos

**0.1 [HUMANO] Confirmar nombres.** En Neon Console → tu proyecto → Branches. Anota los nombres exactos de las dos ramas (se asume `main` para producción y `dev` para desarrollo) y el nombre del rol dueño (normalmente `neondb_owner`) y de la base (normalmente `neondb`). Si difieren, úsalos en todo el documento.

**0.2 [HUMANO] Crear el rol `app_runtime` en las DOS ramas.** Los roles son por rama: crearlo en una no lo crea en la otra.
1. Neon Console → Branches → `dev` → Roles → **New role** → nombre `app_runtime`.
2. Copia la contraseña que muestra (solo se muestra una vez) a tu gestor de contraseñas.
3. Repite en la rama `main`.

**0.3 [HUMANO] Obtener cuatro cadenas de conexión.** Neon Console → **Connect** → elige rama, base y rol:

| Variable | Rama | Rol | Connection pooling |
|---|---|---|---|
| `DATABASE_URL` (dev) | `dev` | `app_runtime` | **Activado** (el host contiene `-pooler`) |
| `MIGRATION_DATABASE_URL` (dev) | `dev` | `neondb_owner` | **Desactivado** |
| `DATABASE_URL` (prod) | `main` | `app_runtime` | **Activado** |
| `MIGRATION_DATABASE_URL` (prod) | `main` | `neondb_owner` | **Desactivado** |

Guárdalas en tu gestor de contraseñas. Nunca en un archivo del repo.

**0.4 [HUMANO] Instalar en tu computador:** Git, `uv`, Docker Desktop.

### Verificación Fase 0
- La persona confirma que tiene las 4 cadenas y los nombres del paso 0.1.

---

## 6. Fase 1 · Estructura del repositorio

### 6.1 Crear estructura

```
repo/
  backend/
    app/
      __init__.py
      main.py              # crea la app FastAPI, monta routers, middlewares
      core/
        config.py          # Settings (pydantic-settings)
        db.py              # engine async, sessionmaker, get_db
        security.py        # hash de contraseñas, tokens, cookies
        errors.py          # AppError + manejador + catálogo de códigos
        rate_limit.py      # slowapi
        time.py            # utilidades de zona horaria y fecha local
        phone.py           # normalización de celulares
      models/              # modelos SQLAlchemy (espejo exacto del esquema)
      schemas/             # Pydantic: entrada y salida de la API
      services/
        events.py          # emit_event()
        auth_operator.py
        customers.py
        workdays.py
        weather.py
        sales.py
        claims.py          # link_sale_to_customer, reconcile_spins
        spins.py
        prizes.py
        voids.py
        stats.py
      api/
        deps.py            # get_current_operator, get_current_customer, origin check
        op/                # routers del operador
        c/                 # routers del cliente
        health.py
    migrations/            # Alembic
    scripts/
      create_operator.py
      reset_operator_password.py
      seed.py
      check_grants.py
    tests/
    Dockerfile
    pyproject.toml
    alembic.ini
    .env.example
    docker-compose.test.yml
  .github/workflows/
  .gitignore
```

### 6.2 Inicializar

```bash
cd backend
uv init --python 3.12
uv add fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg alembic "psycopg[binary]" pydantic-settings argon2-cffi slowapi httpx "sentry-sdk[fastapi]"
uv add --dev pytest pytest-asyncio ruff
```

### 6.3 `.gitignore` en la raíz
Incluye como mínimo: `.env`, `.env.*` (excepto `.env.example`), `__pycache__/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `node_modules/`, `dist/`.

### 6.4 `.env.example` (sin valores reales)

```dotenv
APP_ENV=development                 # development | test | production
DATABASE_URL=                       # app_runtime, pooled
MIGRATION_DATABASE_URL=             # neondb_owner, directa
PUBLIC_APP_URL=http://localhost:5173
ALLOWED_ORIGINS=http://localhost:5173
COOKIE_SECURE=false                 # true en producción
DEFAULT_BUSINESS_SLUG=que-fresh
PRIVACY_POLICY_VERSION=2026-10-v1
SENTRY_DSN=
WEATHER_TIMEOUT_SECONDS=2
```

### 6.5 Base de datos local para pruebas: `docker-compose.test.yml`

```yaml
services:
  db:
    image: postgres:17
    environment:
      POSTGRES_USER: owner
      POSTGRES_PASSWORD: owner
      POSTGRES_DB: app_test
    ports: ["5433:5432"]
    volumes:
      - ./tests/init_roles.sql:/docker-entrypoint-initdb.d/init_roles.sql:ro
```

`tests/init_roles.sql`:
```sql
CREATE ROLE app_runtime LOGIN PASSWORD 'runtime';
```

URLs de prueba:
- Dueño: `postgresql://owner:owner@localhost:5433/app_test`
- Runtime: `postgresql://app_runtime:runtime@localhost:5433/app_test`

### Verificación Fase 1
- `docker compose -f docker-compose.test.yml up -d` levanta la base.
- `uv run python -c "import fastapi, sqlalchemy, asyncpg"` no falla.

---

## 7. Fase 2 · Configuración de Alembic

1. `uv run alembic init migrations`
2. En `migrations/env.py`: leer la URL de la variable `MIGRATION_DATABASE_URL`. Si empieza con `postgresql://`, reemplazar el esquema por `postgresql+psycopg://`. Conservar `sslmode` (psycopg lo entiende).
3. `target_metadata = None`: las migraciones se escriben **a mano en SQL** con `op.execute(...)`. No uses autogenerate para este esquema.
4. Usa **strings crudos de Python** (`r"""..."""`) en las migraciones: hay expresiones regulares con `\`.
5. Cada migración tiene `downgrade()` funcional (`DROP` en orden inverso).

### Verificación Fase 2
- `MIGRATION_DATABASE_URL=postgresql://owner:owner@localhost:5433/app_test uv run alembic upgrade head` corre sin errores.

---

## 8. Fase 3 · Esquema (migraciones)

### Convenciones

- IDs: `uuid DEFAULT gen_random_uuid()` (nativo en PostgreSQL 13+, no requiere extensión).
- Fechas y horas: `timestamptz`, siempre UTC. La fecha local de la jornada se guarda como `date`.
- Dinero: `integer` en pesos colombianos. Nunca decimales.
- Estados: `text` + `CHECK`.
- Nombres en inglés, `snake_case`.

### Migración `0001_core` — ejecutar exactamente este SQL, en este orden

```sql
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
```

> Nota: `sale_item.prize_award_id` **no** es único a propósito. Si una venta con premio se anula, el premio vuelve a `active` y puede usarse en otra venta; la línea vieja queda en la venta anulada como historial.

### Migración `0002_views`

```sql
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
```

### Migración `0003_grants`

Debe correr sin fallar aunque `app_runtime` no exista (por eso el bloque condicional).

```sql
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA public TO app_runtime';
    -- R19: la app lee, inserta y actualiza. Nunca borra.
    EXECUTE 'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_runtime';
    -- R20: los eventos solo se leen e insertan.
    EXECUTE 'REVOKE UPDATE ON event FROM app_runtime';
    -- Sin DELETE ni TRUNCATE en ninguna tabla.
    EXECUTE 'REVOKE DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM app_runtime';
    -- Tablas futuras: mismos permisos por defecto.
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO app_runtime';
  ELSE
    RAISE NOTICE 'app_runtime no existe: se omiten permisos';
  END IF;
END $$;
```

> Regla para migraciones futuras: toda tabla nueva de solo-inserción (como `event`) necesita su propio `REVOKE UPDATE`.

### Verificación Fase 3
1. `alembic upgrade head` y luego `alembic downgrade base` y otra vez `upgrade head`, sin errores, contra la base local.
2. Pruebas de restricciones de la sección 13.1 en verde.

---

## 9. Fase 4 · Datos iniciales (`scripts/seed.py`)

Script **idempotente** (se puede correr varias veces sin duplicar): busca por `business.slug`, `product.name` y `prize_catalog.name`, e inserta o actualiza. Conecta con `MIGRATION_DATABASE_URL`.

### 9.1 Negocio

| Campo | Valor |
|---|---|
| slug | `que-fresh` |
| name | `Qué Fresh` |
| timezone | `America/Bogota` |
| latitude / longitude | **[HUMANO]** confirmar coordenadas del Parque de Rampas, Cedritos (aproximado: 4.723, -74.042) |
| milestone_every | 5 |
| branding | ver abajo |

```json
{
  "display_name": "Qué Fresh",
  "tagline": "Antojo libre de culpa",
  "logo_url": null,
  "colors": { "primary": "#E07AA6", "secondary": "#5DA57E", "ink": "#1A1A1A", "background": "#F4F1EC" },
  "privacy_policy_url": null
}
```
**[HUMANO]** confirmar colores exactos y subir el logo.

### 9.2 Productos (menú real)

**[HUMANO]** completar precio de cada uno (el menú dice entre 12.000 y 16.000). `cost_cop` queda `NULL` hasta que se mida.

| sort_order | name |
|---|---|
| 1 | Berry Bliss |
| 2 | Blue Mist |
| 3 | Sunset Passion |
| 4 | Strawberry Soda |
| 5 | Passion Soda |
| 6 | Green Chai Latte |
| 7 | Amber Matcha Latte |

### 9.3 Catálogo de premios (borrador)

| name | short_label | type | value | max_value_cop | weight | color |
|---|---|---|---|---|---|---|
| 10% de descuento | 10% dto | percent_off | 10 | 16000 | 40 | primary |
| Cold foam o topping extra | Topping | extra_item | 0 | null | 25 | secondary |
| 20% de descuento | 20% dto | percent_off | 20 | 16000 | 20 | primary |
| 50% de descuento | 50% dto | percent_off | 50 | 16000 | 10 | ink |
| Bebida gratis | Gratis | free_item | 0 | 16000 | 5 | ink |

`expires_days = 90` en todos.

### 9.4 Operadores
**No** se crean en el seed. Se crean con `scripts/create_operator.py` (Fase 6.4).

### Verificación Fase 4
- Correr `seed.py` dos veces seguidas: la segunda no crea filas nuevas.

---

## 10. Fase 5 · Núcleo de la aplicación

### 10.1 `core/config.py`
Clase `Settings` con todas las variables de `.env.example`. `ALLOWED_ORIGINS` se parsea como lista separada por comas.

### 10.2 `core/db.py` — conexión (detalles críticos)

Las cadenas de Neon traen `?sslmode=require&channel_binding=require`. **asyncpg no acepta esos parámetros en la URL.** Implementa `to_asyncpg_url(url)`:
1. Cambiar el esquema a `postgresql+asyncpg://`.
2. Eliminar los parámetros `sslmode` y `channel_binding` de la query.
3. Si la URL original tenía `sslmode=require`, pasar `ssl="require"` en `connect_args`.

Crear el engine así:

```python
engine = create_async_engine(
    to_asyncpg_url(settings.DATABASE_URL),
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,          # sobrevive al despertar de Neon
    pool_recycle=300,
    connect_args={
        "ssl": "require",        # solo si la URL original lo pedía
        # El pooler de Neon trabaja en modo transacción: desactivar caché de sentencias preparadas
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
)
```

- `async_sessionmaker(engine, expire_on_commit=False)`.
- Dependencia `get_db()` que entrega una sesión.
- **Cada acción que escribe corre dentro de `async with session.begin():`** — todo o nada.

### 10.3 `core/errors.py`

Clase `AppError(code: str, status: int, message: str, extra: dict | None)`. Manejador global que responde **siempre** con este formato:

```json
{ "error": { "code": "claim_already_claimed", "message": "Esta compra ya fue reclamada.", "extra": {} } }
```

- Los errores de validación de Pydantic se convierten a `validation_error` (422) con el mismo formato.
- Cualquier excepción no controlada → `internal_error` (500), se reporta a Sentry, **sin** detalles internos en la respuesta.
- `IntegrityError` de restricciones conocidas (ver tabla 14.3) se traduce a su código. Nunca devolver el mensaje crudo de PostgreSQL.

### 10.4 `core/security.py`

- `hash_password(p)` y `verify_password(p, h)` con `argon2.PasswordHasher()` (parámetros por defecto).
- `new_token()` = `secrets.token_urlsafe(32)`.
- `hash_token(t)` = SHA-256 hexadecimal. **En la base solo se guarda el hash.**
- `set_session_cookie(response, name, token, max_age)` con: `httponly=True`, `secure=settings.COOKIE_SECURE`, `samesite="lax"`, `path="/"`, **sin atributo `domain`** (así la cookie queda del dominio del frontend, que hace de proxy).
- Nombres de cookie: `op_session` (operador, 30 días) y `c_session` (cliente, 365 días).

### 10.5 Protección contra peticiones de otros sitios (CSRF)

Middleware: para métodos `POST`, `PUT`, `PATCH`, `DELETE`:
1. Si viene cabecera `Origin` y **no** está en `ALLOWED_ORIGINS` → `403 forbidden_origin`.
2. Exigir `Content-Type: application/json` (excepto exportaciones GET, que no aplican).

Junto con `SameSite=Lax`, esto basta. **No** instales middleware CORS: el frontend y la API comparten origen.

### 10.6 `core/rate_limit.py`

`slowapi` en memoria (una sola instancia en Railway). Límites:

| Endpoint | Límite | Clave |
|---|---|---|
| `POST /api/op/auth/login` | 5 / 15 min | email en minúsculas |
| `POST /api/op/auth/login` | 20 / 15 min | IP |
| `POST /api/c/register`, `/api/c/identify/confirm` | 10 / 10 min | IP |
| `POST /api/c/register`, `/api/c/identify/confirm` | 5 / 10 min | `claim_token` |
| `GET /api/c/claims/{token}` | 30 / min | IP |
| `POST /api/c/events`, `/api/op/events` | 60 / min | IP |

IP del cliente: primer valor de `X-Forwarded-For`; si no existe, la IP de la conexión. Uvicorn arranca con `--proxy-headers --forwarded-allow-ips="*"`.

### 10.7 `core/time.py`
- `now_utc()`.
- `local_today(tz)` → `date` en la zona del negocio.
- `end_of_local_day(tz)` → `timestamptz` del siguiente medianoche local.
- `day_type(local_date)` → `'sunday'` si es domingo; si no, `'holiday'` si la fecha está en una lista de festivos de Colombia en `core/holidays.py` (cargar 2026 y 2027 a mano); si no, `'other'`.

### 10.8 `core/phone.py`
`normalize_phone(raw) -> str`:
1. Quitar todo lo que no sea dígito.
2. Si queda con 12 dígitos y empieza por `57`, quitar el `57`.
3. Debe quedar con 10 dígitos y empezar por `3`. Si no → `AppError("invalid_phone", 422)`.
4. Devolver `+57` + los 10 dígitos.

Pruebas: `"310 123 4567"`, `"3101234567"`, `"+57 310-123-4567"`, `"573101234567"` → `+573101234567`. `"6011234567"`, `"31012345"`, `""` → error.

### 10.9 `services/events.py`

```python
async def emit_event(db, *, business_id, type, actor, actor_id=None,
                     customer_id=None, sale_id=None, workday_id=None,
                     payload=None, client_ts=None) -> None
```
- Inserta en `event` **usando la misma sesión y transacción** del llamador. Nunca abre su propia transacción.
- `type` debe estar en la constante `EVENT_TYPES` (sección 14.4). Si no → excepción de programación.

### 10.10 Modelos SQLAlchemy
Un modelo por tabla, **espejo exacto** de la migración (mismos nombres, tipos y nulabilidad). No declares restricciones en los modelos que no existan en la base.

### 10.11 `/api/health`
`GET /api/health` → ejecuta `SELECT 1` → `{"status": "ok"}`. Sin autenticación.

### Verificación Fase 5
- Pruebas unitarias de `normalize_phone`, `to_asyncpg_url`, `hash_token`, `day_type`.
- `GET /api/health` responde 200 contra la base local.

---

## 11. Fase 6 · Servicios y endpoints

Convenciones de toda la API:
- Prefijo `/api`. Operador en `/api/op/*`, cliente en `/api/c/*`.
- JSON con `snake_case`. Dinero en enteros COP. Fechas en ISO 8601 UTC.
- **Orden de bloqueos** para evitar interbloqueos, siempre: `sale` → `customer` → `spin` → `prize_award`. Usa `SELECT ... FOR UPDATE`.
- Toda respuesta de cliente muestra el celular solo como `phone_last4`. Nunca el número completo.

### 11.1 Autenticación del operador

**Scripts**
- `scripts/create_operator.py`: pide por consola slug del negocio, email, nombre, rol y contraseña (con `getpass`, dos veces). Contraseña mínimo 12 caracteres. Guarda el hash. Email en minúsculas.
- `scripts/reset_operator_password.py`: pide email y nueva contraseña; actualiza el hash y **revoca todas sus sesiones** (`revoked_at = now()`).
- Ambos usan `MIGRATION_DATABASE_URL`.

**`POST /api/op/auth/login`** `{ "email", "password" }`
1. Normalizar email a minúsculas. Aplicar límites.
2. Buscar operador activo por email.
3. Si no existe: **igual** ejecutar `verify_password` contra un hash ficticio (para que el tiempo de respuesta no revele si el email existe) y responder `invalid_credentials` 401.
4. Si la contraseña no coincide → `invalid_credentials` 401.
5. Crear `operator_session` con `expires_at = now + 30 días`, `user_agent`.
6. Poner cookie `op_session`.
7. Evento `operator_logged_in`.
8. Responder `{ operator: {id, name, role}, business: {id, name, slug, branding} }`.

**`POST /api/op/auth/logout`** → `revoked_at = now()`, borrar cookie, 204.

**`GET /api/op/auth/me`** → mismo cuerpo que el login.

**Dependencia `get_current_operator`** (la usan TODOS los endpoints `/api/op/*` salvo login):
1. Leer cookie `op_session`. Si falta → `not_authenticated` 401.
2. Buscar sesión por `hash_token`. Debe existir, `revoked_at IS NULL`, `expires_at > now()`, operador `active`. Si no → 401.
3. Entregar el operador (con su `business_id`).

**Dependencia `require_owner`**: igual, y además `role = 'owner'`, si no `forbidden` 403.

### 11.2 Jornada

**`GET /api/op/workdays/current`** → jornada abierta del negocio o `null`.

**`POST /api/op/workdays/open`**
1. `local_date = local_today(business.timezone)`.
2. Si ya hay jornada abierta → `workday_already_open` 409 (devolver su id en `extra`).
3. Si ya existe una jornada **cerrada** con esa fecha → **se reabre** (respuesta 200): `status='open'`, `closed_at`/`closed_by` a `NULL`, los QR pendientes de esa jornada vuelven a vencer al final del día local (R7) y evento `workday_reopened`. Una jornada por fecha: todas las ventas del día quedan en la misma. *Decisión del dueño (2026-10-13); antes era `workday_already_closed_today` 409.*
4. Consultar clima (11.3). Si falla, continuar sin clima.
5. Insertar con `day_type(local_date)`, `opened_by`.
6. Evento `workday_opened` con `{weather_temp_c, weather_code, day_type}`.

**`POST /api/op/workdays/current/close`**
1. Bloquear la jornada abierta. Si no hay → `workday_not_open` 409.
2. `status='closed'`, `closed_at`, `closed_by`.
3. Vencer QR pendientes: `UPDATE sale SET claim_expires_at = now() WHERE workday_id = … AND status = 'paid' AND claim_expires_at > now()`.
4. Evento `workday_closed` con el resumen.
5. Responder el resumen de `v_workday_summary`.

**`GET /api/op/workdays/{id}/sales`** → todas las ventas de la jornada (anuladas incluidas), más recientes primero, con líneas y cliente. `workday_not_found` 404 si no es del negocio.

**Regla transversal:** todo endpoint que crea ventas, vincula o redime exige jornada abierta → si no, `workday_not_open` 409.

### 11.3 Clima (`services/weather.py`)
- `GET https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,weather_code&timezone=America/Bogota`
- `httpx.AsyncClient` con timeout `WEATHER_TIMEOUT_SECONDS`.
- Devuelve `(temp_c, weather_code)` o `(None, None)` ante cualquier error. **Nunca** lanza excepción.
- Si el negocio no tiene coordenadas, no llama.

### 11.4 Catálogo para el operador
- **`GET /api/op/products`** → productos activos ordenados por `sort_order`: `{id, name, price_cop, photo_url}`.

### 11.5 Crear venta — `POST /api/op/sales`

Cabecera obligatoria `Idempotency-Key: <uuid>`. Si falta o no es UUID → `validation_error`.

Cuerpo:
```json
{
  "items": [{ "product_id": "uuid", "qty": 2 }],
  "payment_method": "cash",
  "customer_id": null,
  "prize_award_id": null,
  "prize_target_product_id": null
}
```

Validaciones de entrada:
- `items` entre 1 y 30 líneas; `qty` entre 1 y 20; sin `product_id` repetido.
- `payment_method` en `cash|nequi|breb|card`.
- Si viene `prize_award_id` → `customer_id` y `prize_target_product_id` obligatorios.

Proceso, **en una transacción**:
1. Si ya existe una venta con esa `idempotency_key` y es del mismo negocio → devolverla tal cual (200). No crear nada.
2. Exigir jornada abierta.
3. Cargar los productos pedidos: deben existir, ser del negocio y estar activos. Si no → `product_invalid` 422.
4. Construir líneas: `label = product.name`, `unit_price_cop = product.price_cop`, `unit_cost_cop = product.cost_cop`, `discount_cop = 0`.
5. Si viene `customer_id`: bloquear el cliente; debe ser del negocio → si no, `customer_not_found` 404.
6. Si viene premio → **aplicar premio al crear** (11.9.1).
7. `total_cop = Σ (unit_price_cop × qty − discount_cop)`.
8. Generar `claim_token = secrets.token_urlsafe(24)` y `claim_expires_at = end_of_local_day`.
9. Insertar la venta con `status='paid'` e insertar las líneas.
10. Evento `sale_paid` con `{total_cop, payment_method, items: [{product_id, qty}]}`.
11. Si viene `customer_id` → llamar `link_sale_to_customer(sale, customer, method='manual', actor=operador)` (11.7). Queda `claimed`.
12. Si se aplicó premio → marcar el premio redimido (11.9.1) y evento `prize_redeemed`.
13. Si dos peticiones con la misma clave compiten y una falla por `UNIQUE (idempotency_key)`: capturar `IntegrityError`, hacer rollback, releer y devolver la existente.

Respuesta 201:
```json
{
  "id": "uuid",
  "status": "paid",
  "total_cop": 42000,
  "payment_method": "cash",
  "items": [{ "label": "Berry Bliss", "qty": 2, "unit_price_cop": 14000, "discount_cop": 0 }],
  "claim_url": "https://<PUBLIC_APP_URL>/c/claim/<token>",
  "claim_expires_at": "…",
  "customer": null
}
```

### 11.6 Otros endpoints de venta

**`GET /api/op/sales/{id}`** → detalle completo de la venta.

**`GET /api/op/sales/{id}/status`** — lo consulta el frontend cada 2 segundos mientras muestra el QR:
```json
{ "status": "claimed",
  "customer": { "id": "…", "alias": "Ana", "phone_last4": "4567",
                "purchases": 4, "active_prizes": [ { "id": "…", "name": "…", "type": "…", "expires_at": "…" } ] } }
```
`customer` es `null` si la venta sigue `paid`.

**`POST /api/op/sales/{id}/link`** `{ "customer_id" }` (vínculo manual, F4):
1. Bloquear venta: del negocio, `status='paid'`, jornada de la venta **abierta**. Si no → `sale_not_linkable` 409.
2. Llamar `link_sale_to_customer(method='manual')`.
3. Evento adicional `sale_linked_manual`.

**`POST /api/op/sales/{id}/unlink`** ("No es Ana"):
1. Bloquear venta: `status='claimed'`, jornada abierta. Si no → `sale_not_linkable` 409.
2. Si la venta tiene un premio redimido → `sale_has_prize` 409 (hay que anularla, no desvincularla).
3. Ejecutar la **cascada de giros** de 11.8 pasos 3–4 (sin tocar el estado de la venta todavía).
4. Volver la venta a `paid`: `customer_id = NULL`, `claimed_at = NULL`, `claim_method = NULL`.
5. `reconcile_spins(cliente anterior)`.
6. Evento `sale_unlinked`.

**`POST /api/op/sales/{id}/void`** `{ "reason": "texto 3-200 caracteres" }` → ver 11.8.

**`GET /api/op/customers/search?last4=4567`**
- `last4` exactamente 4 dígitos.
- Clientes del negocio con `right(phone,4) = last4`, máximo 10.
- Respuesta: `[{ id, alias, phone_last4, purchases, active_prizes_count }]`.

**`GET /api/op/customers/{id}`** → ficha: `alias`, `phone_last4`, `purchases`, `milestone_every`, `active_prizes` (con vencimiento), últimas 20 ventas.

### 11.7 Vincular compra a cliente — `services/claims.py` (función central)

**Todos** los caminos de vinculación usan esta función: QR de cliente con sesión, registro, confirmación de identidad, vínculo manual y venta creada con cliente.

```python
async def link_sale_to_customer(db, sale, customer, method, actor, actor_id) -> ClaimResult
```

Precondición: la venta ya está bloqueada `FOR UPDATE` por el llamador.

1. Validar la venta:
   - `status == 'void'` → `claim_voided` 410.
   - `status == 'claimed'` → `claim_already_claimed` 409.
   - `method == 'qr'` y `claim_expires_at <= now()` → `claim_expired` 410.
   - `sale.business_id != customer.business_id` → `claim_not_found` 404.
2. Bloquear el cliente `FOR UPDATE`.
3. `counted = stamps.earns_stamp(...)` (R8; con la regla actual siempre es verdadero).
4. Actualizar venta: `customer_id`, `status='claimed'`, `claimed_at=now()`, `claim_method=method`.
5. Evento `sale_claimed` con `{method, counted}`.
6. `new_spins = await reconcile_spins(db, customer, trigger_sale=sale)`.
7. Devolver `ClaimResult(counted, new_spins, card=build_card(customer))`.

```python
async def reconcile_spins(db, customer, trigger_sale=None) -> list[Spin]
```
Hace que los giros vigentes coincidan con las compras (R9, R10). Se llama tras vincular, desvincular y anular.

1. `purchases` = `stamps.count_stamps(...)` (R8). La vista `v_customer_purchases` se eliminó en `0004`.
2. `every = business.milestone_every`.
3. Giros esperados: `welcome` si `purchases >= 1`; `milestone n` para cada `n` en `every, 2·every, …, ≤ purchases`.
4. Giros vigentes = los del cliente con `status <> 'void'`.
5. **Crear** los esperados que faltan, con `status='available'` y `unlocked_by_sale_id` = `trigger_sale.id` si existe; si no, la venta `claimed` más reciente del cliente. Evento `spin_unlocked` por cada uno.
6. **Anular** los giros `available` que ya no están justificados (`milestone_n > purchases`, o `welcome` si `purchases = 0`): `status='void'`, `voided_at`. Evento `spin_voided`.
7. Nunca tocar giros `consumed` aquí.
8. Devolver los giros creados.

`build_card(customer)`:
```json
{
  "customer": { "id": "…", "alias": "Ana", "phone_last4": "4567" },
  "purchases": 4,
  "milestone_every": 5,
  "progress": 4,
  "purchases_to_next_spin": 1,
  "available_spins": [{ "id": "…", "reason": "milestone", "milestone_n": 5 }],
  "active_prizes": [{ "id": "…", "name": "…", "short_label": "…", "type": "…", "awarded_at": "…", "expires_at": "…" }]
}
```
- `progress = purchases % every`; si `purchases > 0` y `progress == 0`, mostrar `progress = every`.
- `purchases_to_next_spin = every - (purchases % every)`.
- `active_prizes`: `status='active'` y `expires_at > now()`.

### 11.8 Anular venta — `services/voids.py`

`POST /api/op/sales/{id}/void`, en una transacción:
1. Bloquear la venta del negocio. Si ya es `void` → `sale_already_void` 409.
2. Permisos: `operator` solo puede anular ventas de la jornada abierta; `owner` cualquiera.
3. **Cascada de giros** — para cada giro con `unlocked_by_sale_id = venta`:
   - `available` → `void`, `voided_at`. Evento `spin_voided`.
   - `consumed` y su premio está `active` → premio a `void` (`voided_at`), giro a `void` (`voided_at`). Eventos `prize_voided` y `spin_voided`.
   - `consumed` y su premio está `redeemed` → no tocar. Evento `void_left_redeemed_prize` para auditoría.
4. **Premio usado en esta venta** (`prize_award.redeemed_sale_id = venta`): volver a `active`, limpiar `redeemed_at`, `redeemed_sale_id`, `redeemed_by`. Evento `prize_restored`.
5. Venta: `status='void'`, `voided_at`, `voided_by`, `void_reason`. Si estaba `claimed`, **conserva** `customer_id` como historial.
6. Si había cliente: `reconcile_spins(cliente)` (puede recrear un giro de bienvenida si otra venta lo justifica).
7. Evento `sale_voided` con `{reason, previous_status}`.

### 11.9 Premios

#### 11.9.1 Aplicar premio al crear una venta (paso 6 de 11.5)
1. Bloquear el premio. Validar:
   - Existe, es del negocio y del `customer_id` → si no, `prize_not_found` 404 (mismo error si es de otro cliente: no revelar).
   - `status == 'active'` → si no, `prize_not_active` 409.
   - `expires_at > now()` → si no, `prize_expired` 410.
2. `prize_target_product_id` debe estar en `items` → si no, `prize_target_invalid` 422.
3. Según el tipo (R17), sobre **una unidad**:
   - `percent_off`: `discount = min(round(price × value / 100), max_value_cop o price)`. Sumar al `discount_cop` de la línea del producto objetivo y poner su `prize_award_id`.
   - `free_item`: `discount = min(price, max_value_cop o price)`. Igual que arriba.
   - `extra_item`: agregar una línea nueva `product_id=NULL`, `label = prize.name`, `qty=1`, `unit_price_cop=0`, `discount_cop=0`, `prize_award_id`.
4. Tras insertar la venta: premio `status='redeemed'`, `redeemed_at`, `redeemed_sale_id`, `redeemed_by`.
5. Si falla el índice `prize_one_per_sale` → `prize_already_in_sale` 409.

#### 11.9.2 Redimir sobre una venta ya cobrada — `POST /api/op/sales/{id}/redeem-prize`
Cuerpo: `{ "prize_award_id", "product_id" }` (`product_id` obligatorio para `free_item`, ignorado para `extra_item`).
1. Bloquear venta: `status='claimed'`, jornada abierta. Si no → `sale_not_linkable` 409.
2. Bloquear premio y validar como en 11.9.1 paso 1, contra el **cliente de la venta**.
3. `percent_off` → `discount_needs_new_sale` 409 (R18).
4. Si la venta ya tiene un premio → `prize_already_in_sale` 409.
5. `free_item`: el producto debe ser del negocio y activo. Agregar línea `product_id`, `label`, `qty=1`, `unit_price_cop = price`, `unit_cost_cop = cost`, `discount_cop = min(price, max_value_cop o price)`, `prize_award_id`. Si el tope es menor que el precio, **no** se cobra la diferencia en este flujo: responder `prize_target_invalid` 422 y pedir hacerlo como venta nueva.
6. `extra_item`: línea `product_id=NULL`, `label=prize.name`, `qty=1`, precio 0.
7. `total_cop` **no cambia** (neto 0).
8. Premio a `redeemed`. Evento `prize_redeemed`.

#### 11.9.3 Consultas
- **`GET /api/op/prizes/pending?filter=expiring|free|all`** → desde `v_pending_prizes` del negocio. `expiring` = vencen en ≤ 7 días. `free` = tipos `free_item`. Orden por `expires_at`.
- **`GET /api/op/prizes/catalog`** (`require_owner`) → catálogo completo **con** pesos. Solo para el dueño.

### 11.10 Identidad del cliente

**`GET /api/c/business`** → `{ name, slug, branding, privacy_policy_version }` del negocio por defecto (`DEFAULT_BUSINESS_SLUG`) o del cliente con sesión. Sin autenticación.

**`GET /api/c/claims/{token}`** — vista previa para la pantalla de entrada, sin datos personales:
```json
{ "state": "claimable", "sale": { "items_count": 2, "total_cop": 28000, "paid_at": "…" }, "business": { "name": "…", "branding": {} } }
```
`state`: `claimable` | `already_claimed` | `expired` | `voided` | `not_found`. Siempre 200 (salvo límite de intentos).

**`POST /api/c/register`** `{ "phone", "alias", "consent": true, "claim_token" }`
1. `consent` debe ser `true` → si no, `consent_required` 422.
2. `alias`: recortar espacios, 2 a 30 caracteres.
3. `phone = normalize_phone(phone)`.
4. Bloquear la venta por `claim_token` → si no existe, `claim_not_found` 404. Validar como en 11.7 paso 1 (método `qr`) **antes** de crear nada.
5. Si ya existe cliente con ese teléfono en el negocio → `customer_exists` 409 con `extra: { "alias": "Ana", "phone_last4": "4567" }`. **Solo aquí** se revela el alias, y solo porque hay un token válido (R5).
6. Crear cliente con `consent_at=now()`, `consent_version=PRIVACY_POLICY_VERSION`. Evento `customer_created`.
7. Crear `customer_session` (365 días). Cookie `c_session`.
8. `link_sale_to_customer(method='qr', actor='customer')`.
9. Responder `{ card, counted, new_spins }`.

**`POST /api/c/identify/confirm`** `{ "phone", "claim_token" }`
1. Normalizar teléfono. Bloquear y validar la venta como en register paso 4.
2. Buscar cliente por teléfono en el negocio de la venta → si no existe, `customer_not_found` 404.
3. Crear sesión nueva y cookie. Evento `identity_confirmed`.
4. `link_sale_to_customer(method='qr')`.
5. Responder igual que register.

**Dependencia `get_current_customer`**: como la del operador, con `c_session`. Si falta o es inválida → `not_authenticated` 401.

**`GET /api/c/me`** → `build_card(customer)`.

**`POST /api/c/claim`** `{ "claim_token" }` (cliente con sesión, F2)
1. Bloquear la venta por token. Si no existe → `claim_not_found` 404.
2. `link_sale_to_customer(method='qr')`.
3. Responder `{ card, counted, new_spins }`.

**`GET /api/c/history`** → últimas 30 ventas del cliente (no anuladas): fecha, líneas, total, premio usado.

**`POST /api/c/logout`** → revoca la sesión y borra la cookie.

### 11.11 Ruleta

**`GET /api/c/wheel`** → casillas activas **sin pesos**, en `sort_order`:
```json
{ "segments": [ { "id": "…", "short_label": "10% dto", "color": "primary" } ] }
```

**`POST /api/c/spins/{id}/spin`** (con sesión de cliente)
1. Bloquear el giro. Debe ser del cliente de la sesión → si no, `spin_not_found` 404.
2. Si `status='consumed'` → devolver el premio existente (idempotente, R12).
3. Si `status='void'` → `spin_not_available` 409.
4. Cargar premios activos del negocio. Si no hay → `internal_error` y alerta a Sentry.
5. Elegir con `secrets.SystemRandom().choices(premios, weights=[p.weight …], k=1)`. El generador se inyecta como parámetro del servicio para poder probarlo.
6. Insertar `prize_award` con `expires_at = now() + expires_days`.
7. Giro a `consumed`, `spun_at=now()`.
8. Eventos `spin_started` y `prize_awarded`.
9. Responder:
```json
{ "segment_index": 2,
  "prize_award": { "id": "…", "name": "…", "short_label": "…", "type": "…", "expires_at": "…" },
  "card": { } }
```
`segment_index` = posición del premio en la lista de `GET /api/c/wheel`.

**`GET /api/c/prizes/{id}`** → detalle del premio del cliente, incluido `status` (la pantalla "Quiero usar mi premio" lo consulta para actualizarse cuando el operador redime). Si está `active` y `expires_at <= now()`, devolver `status: "expired"`.

### 11.12 Estadísticas (solo operador)

| Endpoint | Fuente | Respuesta |
|---|---|---|
| `GET /api/op/stats/workdays/{id}` | `v_workday_summary`, `v_hourly_sales`, `v_product_sales` | Resumen + `drinks_per_sale` + `claimed_pct` + ventas por hora + top 3 productos + mejor hora |
| `GET /api/op/stats/history?from=YYYY-MM-DD&to=YYYY-MM-DD` | Mismas vistas | Lista de jornadas + ranking de productos del rango + promedio por hora |
| `GET /api/op/export/sales.csv?from&to` (`require_owner`) | `sale` + `sale_item` | CSV, una fila por línea de venta |

- `drinks_per_sale = drinks / sales` redondeado a 2 decimales.
- `claimed_pct = claimed_sales / sales` (0 si no hay ventas).
- Si hay productos sin costo, incluir `cost_incomplete: true` y **no** mostrar margen.

### 11.13 Eventos desde el frontend

**`POST /api/c/events`** y **`POST /api/op/events`**:
```json
{ "type": "page_loaded", "sale_id": null, "payload": { "load_ms": 1400 }, "client_ts": "…" }
```
Solo tipos permitidos:
- Cliente: `qr_scanned`, `page_loaded`, `register_viewed`, `identity_rejected`, `card_viewed`, `install_prompt_shown`, `install_prompt_accepted`.
- Operador: `sale_qr_shown`, `sale_skipped`.

`payload` máximo 2 KB. El actor se toma de la sesión si existe (el cliente puede no tener sesión: entonces `actor_id = null`).

### Verificación Fase 6
- Cada endpoint aparece en `/api/docs`.
- Todas las pruebas de la sección 13 en verde.

---

## 12. Fase 7 · Seguridad (checklist obligatorio)

- [ ] Contraseñas con argon2; nunca registradas en logs.
- [ ] Tokens de sesión: solo el hash en la base.
- [ ] Cookies `HttpOnly`, `Secure` en producción, `SameSite=Lax`, sin `domain`.
- [ ] Todos los `/api/op/*` exigen `get_current_operator`, salvo login.
- [ ] Todo acceso filtra por `business_id` del usuario autenticado (R21).
- [ ] Middleware de origen para métodos que escriben.
- [ ] Límites de intentos configurados.
- [ ] Registro e identificación exigen `claim_token` válido (R5).
- [ ] Respuestas de cliente solo con `phone_last4`.
- [ ] Pesos de premios nunca en endpoints de cliente.
- [ ] Precios nunca aceptados desde el frontend.
- [ ] Errores sin detalles internos; Sentry recibe el detalle.
- [ ] `app_runtime` sin `DELETE`, sin `UPDATE` en `event` (comprobado con `check_grants.py`).
- [ ] Documentación `/api/docs` deshabilitada en producción (`docs_url=None` si `APP_ENV=production`); el esquema OpenAPI se exporta a archivo para el frontend.
- [ ] Ninguna credencial del rol dueño en Railway.

---

## 13. Fase 8 · Pruebas

### Configuración
- Base local de `docker-compose.test.yml`.
- Fixture de sesión: `alembic upgrade head` sobre `app_test` usando la URL del dueño.
- Entre pruebas: `TRUNCATE` de todas las tablas (como dueño) y recargar un seed mínimo de prueba.
- La app en pruebas se conecta como **`app_runtime`**, igual que en producción.
- Fixtures: `business`, `operator` + cliente HTTP autenticado, `open_workday`, `products`, `prize_catalog`, `rng` determinístico.

### 13.1 Restricciones de la base (`tests/db/`)
Conectado como dueño, cada inserción debe **fallar**:

| Prueba | Espera |
|---|---|
| Dos clientes con el mismo celular en el negocio | Rechazo por unicidad |
| Celular `3101234567` sin `+57` | Rechazo por formato |
| Segundo giro `welcome` vigente para el cliente | Rechazo |
| Dos giros vigentes para el mismo hito | Rechazo |
| Dos premios `redeemed` con la misma venta | Rechazo |
| Segunda jornada abierta en el negocio | Rechazo |
| Venta `claimed` sin cliente | Rechazo |
| Venta `void` sin motivo | Rechazo |

Conectado como `app_runtime`:

| Prueba | Espera |
|---|---|
| `DELETE` en cualquier tabla | Permiso denegado |
| `UPDATE event` | Permiso denegado |
| `CREATE TABLE` | Permiso denegado |

Y: (R8 ahora en `stamps.py`, se prueba en `tests/api`) dos ventas `claimed` del mismo cliente en una jornada → 2 sellos.

### 13.2 Flujos (`tests/flows/`)

| Prueba | Pasos y comprobaciones |
|---|---|
| **F1 Primera compra** | Crear venta → vista previa `claimable` → registrar → giro `welcome` disponible → girar → premio `active`, vence en 90 días → la vista previa pasa a `already_claimed` |
| **F2 Sesión abierta** | Cliente con 4 compras en 4 jornadas → nueva jornada → reclamar → `purchases=5` y aparece giro `milestone 5` |
| **F2 Mismo día** | Segunda venta en la misma jornada → `counted=true`, +1 sello (R8) |
| **F3 Sin sesión** | Registrar con celular existente → 409 con alias → confirmar → sesión nueva, sin giro de bienvenida |
| **F4 Sin escaneo** | Venta anónima → buscar por últimos 4 → vincular manual → `claim_method='manual'` |
| **F5 Premio guardado** | Cliente con `percent_off 10%` → venta con premio sobre producto de 14000 → descuento 1400 en una unidad, total correcto, premio `redeemed` |
| **F5 Tope** | `percent_off 50%` sobre producto de 16000 con tope 16000 → descuento 8000 |
| **F6 Inmediato extra** | Girar → `extra_item` → redimir sobre la venta cobrada → línea de $0, total igual |
| **F6 Descuento inmediato** | `percent_off` sobre venta cobrada → `discount_needs_new_sale` |
| **F7 Jornada** | Abrir (clima simulado) → vender → cerrar → QR pendiente da `expired` → resumen correcto |
| **Clima caído** | API de clima con timeout → la jornada abre sin clima |

### 13.3 Casos borde

| Prueba | Espera |
|---|---|
| Mismo `Idempotency-Key` dos veces en crear venta | Una sola venta |
| Dos reclamos simultáneos del mismo token (`asyncio.gather`) | Uno gana, el otro `claim_already_claimed` |
| Girar dos veces el mismo giro | Mismo premio |
| Giro de otro cliente | `spin_not_found` |
| Premio de otro cliente | `prize_not_found` |
| Dos premios en una venta | `prize_already_in_sale` |
| Premio vencido | `prize_expired` |
| Anular venta que liberó `welcome` disponible | Giro `void` |
| Anular venta cuyo premio ya se ganó y está activo | Premio `void`, giro `void` |
| Anular venta que usó un premio | Premio vuelve a `active` |
| Anular la venta de bienvenida teniendo otra venta del mismo día | `reconcile` crea un nuevo `welcome` |
| Anular la venta que completó el hito 5 | Hito 5 `void`, `purchases=4` |
| Desvincular venta con premio | `sale_has_prize` |
| Registrar sin token o con token vencido | Error, no se crea cliente |
| Registrar sin consentimiento | `consent_required` |
| `/api/op/*` sin cookie | 401 |
| Cookie de cliente en `/api/op/*` | 401 |
| POST con `Origin` ajeno | 403 |
| Login fallido 6 veces | 429 |
| Crear venta con precio en el cuerpo | El precio se ignora; se usa el de la base |

### Verificación Fase 8
- `uv run pytest` 100% en verde.

---

## 14. Referencias

### 14.1 Endpoints

| Método | Ruta | Auth | Sección |
|---|---|---|---|
| GET | `/api/health` | — | 10.11 |
| POST | `/api/op/auth/login` | — | 11.1 |
| POST | `/api/op/auth/logout` | Operador | 11.1 |
| GET | `/api/op/auth/me` | Operador | 11.1 |
| GET | `/api/op/workdays/current` | Operador | 11.2 |
| POST | `/api/op/workdays/open` | Operador | 11.2 |
| POST | `/api/op/workdays/current/close` | Operador | 11.2 |
| GET | `/api/op/products` | Operador | 11.4 |
| POST | `/api/op/sales` | Operador | 11.5 |
| GET | `/api/op/sales/{id}` | Operador | 11.6 |
| GET | `/api/op/sales/{id}/status` | Operador | 11.6 |
| POST | `/api/op/sales/{id}/link` | Operador | 11.6 |
| POST | `/api/op/sales/{id}/unlink` | Operador | 11.6 |
| POST | `/api/op/sales/{id}/void` | Operador | 11.8 |
| POST | `/api/op/sales/{id}/redeem-prize` | Operador | 11.9.2 |
| GET | `/api/op/customers/search` | Operador | 11.6 |
| GET | `/api/op/customers/{id}` | Operador | 11.6 |
| GET | `/api/op/prizes/pending` | Operador | 11.9.3 |
| GET | `/api/op/prizes/catalog` | Dueño | 11.9.3 |
| GET | `/api/op/stats/workdays/{id}` | Operador | 11.12 |
| GET | `/api/op/stats/history` | Operador | 11.12 |
| GET | `/api/op/export/sales.csv` | Dueño | 11.12 |
| POST | `/api/op/events` | Operador | 11.13 |
| GET | `/api/c/business` | — | 11.10 |
| GET | `/api/c/claims/{token}` | — | 11.10 |
| POST | `/api/c/register` | — (token) | 11.10 |
| POST | `/api/c/identify/confirm` | — (token) | 11.10 |
| GET | `/api/c/me` | Cliente | 11.10 |
| POST | `/api/c/claim` | Cliente | 11.10 |
| GET | `/api/c/history` | Cliente | 11.10 |
| POST | `/api/c/logout` | Cliente | 11.10 |
| GET | `/api/c/wheel` | — | 11.11 |
| POST | `/api/c/spins/{id}/spin` | Cliente | 11.11 |
| GET | `/api/c/prizes/{id}` | Cliente | 11.11 |
| POST | `/api/c/events` | — / Cliente | 11.13 |

### 14.2 Códigos de error

| Código | HTTP | Mensaje para el usuario |
|---|---|---|
| `validation_error` | 422 | Revisa los datos ingresados. |
| `invalid_phone` | 422 | Ese número no parece un celular colombiano. |
| `consent_required` | 422 | Debes aceptar el tratamiento de datos para continuar. |
| `product_invalid` | 422 | Uno de los productos ya no está disponible. |
| `prize_target_invalid` | 422 | Ese premio no aplica a esa bebida. |
| `invalid_credentials` | 401 | Correo o contraseña incorrectos. |
| `not_authenticated` | 401 | Tu sesión terminó. Ingresa de nuevo. |
| `forbidden` | 403 | No tienes permiso para esta acción. |
| `forbidden_origin` | 403 | Solicitud no permitida. |
| `claim_not_found` | 404 | No encontramos esa compra. |
| `customer_not_found` | 404 | No encontramos ese cliente. |
| `sale_not_found` | 404 | No encontramos esa venta. |
| `spin_not_found` | 404 | No encontramos ese giro. |
| `prize_not_found` | 404 | No encontramos ese premio. |
| `customer_exists` | 409 | (Mostrar pantalla "¿Eres …?") |
| `claim_already_claimed` | 409 | Esta compra ya fue reclamada. |
| `workday_not_open` | 409 | Abre la jornada para vender. |
| `workday_already_open` | 409 | Ya hay una jornada abierta. |
| `workday_already_closed_today` | 409 | La jornada de hoy ya se cerró. |
| `sale_not_linkable` | 409 | Esta venta ya no se puede modificar. |
| `sale_has_prize` | 409 | Esta venta usó un premio: anúlala en lugar de desvincularla. |
| `sale_already_void` | 409 | Esta venta ya estaba anulada. |
| `prize_not_active` | 409 | Este premio ya fue usado. |
| `prize_already_in_sale` | 409 | Solo se puede usar un premio por compra. |
| `discount_needs_new_sale` | 409 | Los descuentos se aplican en una compra nueva. |
| `spin_not_available` | 409 | Este giro ya no está disponible. |
| `claim_expired` | 410 | Este código venció. |
| `claim_voided` | 410 | Esta compra fue anulada. |
| `prize_expired` | 410 | Este premio venció. |
| `rate_limited` | 429 | Demasiados intentos. Espera un momento. |
| `internal_error` | 500 | Algo salió mal. Intenta de nuevo. |

### 14.3 Restricción → código de error

| Restricción / índice | Código |
|---|---|
| `customer_business_id_phone_key` | `customer_exists` |
| `workday_one_open` | `workday_already_open` |
| `workday_business_id_local_date_key` | `workday_already_closed_today` |
| `prize_one_per_sale` | `prize_already_in_sale` |
| `sale_idempotency_key_key` | (reintentar lectura, ver 11.5 paso 13) |
| `spin_one_welcome`, `spin_one_milestone` | Ignorar en `reconcile_spins` (ya existe) |

Verifica los nombres reales de las restricciones generadas por PostgreSQL y ajusta el mapa.

### 14.4 Tipos de evento (`EVENT_TYPES`)

Operador: `operator_logged_in`, `workday_opened`, `workday_closed`, `sale_paid`, `sale_qr_shown`, `sale_skipped`, `sale_linked_manual`, `sale_unlinked`, `sale_voided`, `prize_redeemed`, `prize_restored`, `void_left_redeemed_prize`.

Cliente: `qr_scanned`, `page_loaded`, `register_viewed`, `identity_rejected`, `identity_confirmed`, `customer_created`, `card_viewed`, `install_prompt_shown`, `install_prompt_accepted`, `sale_claimed`, `spin_started`, `prize_awarded`.

Sistema: `spin_unlocked`, `spin_voided`, `prize_voided`.

---

## 15. Fase 9 · Despliegue

### 15.1 Dockerfile

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
ENV PATH="/app/.venv/bin:$PATH"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
```

### 15.2 Migraciones en producción (nunca desde Railway)

`.github/workflows/migrate.yml`, **disparo manual** (`workflow_dispatch`) con entrada `target: dev | main`:
1. Checkout, instalar `uv`, `uv sync`.
2. `alembic upgrade head` con el secreto `MIGRATION_DATABASE_URL_DEV` o `MIGRATION_DATABASE_URL_MAIN`.

**[HUMANO]** GitHub → Settings → Secrets and variables → Actions → crear `MIGRATION_DATABASE_URL_DEV` y `MIGRATION_DATABASE_URL_MAIN`. Crear también el entorno `production` con aprobación requerida para `main`.

### 15.3 Integración continua
`.github/workflows/ci.yml` en cada push y PR: servicio `postgres:17` con el rol `app_runtime`, `ruff check`, `ruff format --check`, `pytest`.

### 15.4 [HUMANO] Railway
1. Nuevo proyecto → Deploy from GitHub → carpeta raíz `backend/` → usa el Dockerfile.
2. Región: la más cercana a la región de Neon.
3. Variables: `APP_ENV=production`, `DATABASE_URL` (**app_runtime, main, pooled**), `PUBLIC_APP_URL=https://<dominio>`, `ALLOWED_ORIGINS=https://<dominio>`, `COOKIE_SECURE=true`, `DEFAULT_BUSINESS_SLUG=que-fresh`, `PRIVACY_POLICY_VERSION`, `SENTRY_DSN`, `WEATHER_TIMEOUT_SECONDS=2`.
4. **No** agregar `MIGRATION_DATABASE_URL` en Railway.
5. Health check: `/api/health`.
6. Plan Hobby (servicio siempre encendido).

### 15.5 Orden de salida a producción
1. Ejecutar el workflow `migrate` con `target=main`.
2. `seed.py` contra `main` desde tu computador (con `MIGRATION_DATABASE_URL` de `main`).
3. `create_operator.py` dos veces (dueño y operador) contra `main`.
4. `check_grants.py` contra `main`: conecta como `app_runtime` e intenta `DELETE` y `UPDATE event` dentro de una transacción que siempre hace rollback; debe reportar "permiso denegado" en ambos.
5. Desplegar en Railway.
6. `GET https://<railway>/api/health` → `ok`.

### 15.6 Exportar el contrato para el frontend
Script `scripts/export_openapi.py` que escribe `openapi.json` (con `app.openapi()`) en `frontend/openapi.json`. Correrlo cada vez que cambie la API.

---

## 16. Entregable final de esta capa

- [ ] Migraciones aplicadas en `dev` y `main`.
- [ ] Seed cargado en ambas ramas.
- [ ] Operadores creados en `main`.
- [ ] `check_grants.py` confirma permisos en `main`.
- [ ] `pytest` en verde en CI.
- [ ] API en Railway respondiendo `/api/health`.
- [ ] `openapi.json` exportado al frontend.
- [ ] Tabla de códigos de error (14.2) entregada al frontend.

## Pendientes de la persona antes de producción
- [ ] Precios de los 7 productos.
- [ ] Costo por producto (puede ir después; sin él no se muestra margen).
- [ ] Coordenadas del punto.
- [ ] Colores y logo.
- [ ] Texto y URL de la política de tratamiento de datos (Ley 1581 de 2012) y su versión.
- [ ] Confirmar catálogo y pesos de premios.
