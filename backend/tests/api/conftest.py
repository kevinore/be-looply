import httpx
import pytest

from app.main import app


@pytest.fixture
async def client(migrated_db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
