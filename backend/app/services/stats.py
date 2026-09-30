from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
