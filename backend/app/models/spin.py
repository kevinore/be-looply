from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Tstz, UuidPk


class Spin(Base):
    __tablename__ = "spin"

    id: Mapped[UuidPk]
    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id"))
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.id"))
    reason: Mapped[str] = mapped_column(Text)
    milestone_n: Mapped[int | None] = mapped_column(Integer)
    unlocked_by_sale_id: Mapped[UUID] = mapped_column(ForeignKey("sale.id"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'available'"))
    created_at: Mapped[CreatedAt]
    spun_at: Mapped[datetime | None] = mapped_column(Tstz)
    voided_at: Mapped[datetime | None] = mapped_column(Tstz)
