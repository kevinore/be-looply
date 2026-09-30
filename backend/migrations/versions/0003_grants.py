"""grants for app_runtime

Revision ID: 0003_grants
Revises: 0002_views
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_grants"
down_revision: str | None = "0002_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Must not fail when app_runtime does not exist (conditional block).
    op.execute(r"""
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
""")


def downgrade() -> None:
    op.execute(r"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE ON TABLES FROM app_runtime';
    EXECUTE 'REVOKE SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public FROM app_runtime';
    EXECUTE 'REVOKE USAGE ON SCHEMA public FROM app_runtime';
  ELSE
    RAISE NOTICE 'app_runtime no existe: se omiten permisos';
  END IF;
END $$;
""")
