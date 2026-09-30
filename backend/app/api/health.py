from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import DbSession

router = APIRouter()


@router.get("/api/health")
async def health(db: DbSession) -> dict:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
