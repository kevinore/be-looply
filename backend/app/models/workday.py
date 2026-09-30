from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Numeric, SmallInteger, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Tstz, UuidPk


class Workday(Base):
    __tablename__ = "workday"

    id: Mapped[UuidPk]
    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id"))
    local_date: Mapped[date] = mapped_column(Date)
    day_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    opened_at: Mapped[datetime] = mapped_column(Tstz, server_default=text("now()"))
    opened_by: Mapped[UUID] = mapped_column(ForeignKey("operator.id"))
    closed_at: Mapped[datetime | None] = mapped_column(Tstz)
    closed_by: Mapped[UUID | None] = mapped_column(ForeignKey("operator.id"))
    weather_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    weather_code: Mapped[int | None] = mapped_column(SmallInteger)
