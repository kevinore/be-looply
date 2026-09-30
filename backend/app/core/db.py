from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# asyncpg does not accept these libpq parameters in the URL.
_LIBPQ_ONLY_PARAMS = {"sslmode", "channel_binding"}


def to_asyncpg_url(url: str) -> str:
    """Switch the scheme to postgresql+asyncpg and drop sslmode/channel_binding."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in _LIBPQ_ONLY_PARAMS]
    return urlunsplit(
        ("postgresql+asyncpg", parts.netloc, parts.path, urlencode(query), "")
    )


def requires_ssl(url: str) -> bool:
    return dict(parse_qsl(urlsplit(url).query)).get("sslmode") == "require"


def build_connect_args(url: str) -> dict:
    connect_args: dict = {
        # Neon's pooler runs in transaction mode: disable prepared statement caches.
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }
    if requires_ssl(url):
        connect_args["ssl"] = "require"
    return connect_args


engine = create_async_engine(
    to_asyncpg_url(settings.DATABASE_URL),
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,  # survives Neon waking up
    pool_recycle=300,
    connect_args=build_connect_args(settings.DATABASE_URL),
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    # Every write action runs inside `async with session.begin():` (all or nothing).
    async with SessionLocal() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
