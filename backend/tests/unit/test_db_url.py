from app.core.db import build_connect_args, to_asyncpg_url

NEON = (
    "postgresql://app_runtime:secret@ep-x-pooler.us-east-2.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)


def test_neon_url_is_converted():
    assert (
        to_asyncpg_url(NEON)
        == "postgresql+asyncpg://app_runtime:secret@ep-x-pooler.us-east-2.aws.neon.tech/neondb"
    )


def test_neon_url_requires_ssl():
    args = build_connect_args(NEON)
    assert args["ssl"] == "require"
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0


def test_local_url_without_ssl():
    url = "postgresql://app_runtime:runtime@localhost:5433/app_test"
    assert to_asyncpg_url(url) == (
        "postgresql+asyncpg://app_runtime:runtime@localhost:5433/app_test"
    )
    assert "ssl" not in build_connect_args(url)


def test_other_query_params_are_kept():
    url = "postgresql://u:p@h/db?sslmode=require&application_name=api"
    assert to_asyncpg_url(url) == "postgresql+asyncpg://u:p@h/db?application_name=api"
