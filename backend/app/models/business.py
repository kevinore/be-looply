from decimal import Decimal

from sqlalchemy import Numeric, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPk


class Business(Base):
    __tablename__ = "business"

    id: Mapped[UuidPk]
    slug: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, server_default=text("'America/Bogota'"))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    branding: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    milestone_every: Mapped[int] = mapped_column(SmallInteger, server_default=text("5"))
    created_at: Mapped[CreatedAt]
