from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Tstz, UuidPk


class OperatorSession(Base):
    __tablename__ = "operator_session"

    id: Mapped[UuidPk]
    operator_id: Mapped[UUID] = mapped_column(ForeignKey("operator.id"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[CreatedAt]
    expires_at: Mapped[datetime] = mapped_column(Tstz)
    revoked_at: Mapped[datetime | None] = mapped_column(Tstz)
