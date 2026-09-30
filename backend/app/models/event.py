from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Tstz, UuidPk


class Event(Base):
    """Insert-only (R20). actor_id, customer_id, sale_id and workday_id have no FK."""

    __tablename__ = "event"

    id: Mapped[UuidPk]
    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id"))
    type: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    customer_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    sale_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    workday_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    client_ts: Mapped[datetime | None] = mapped_column(Tstz)
    server_ts: Mapped[datetime] = mapped_column(Tstz, server_default=text("now()"))
