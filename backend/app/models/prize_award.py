from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Tstz, UuidPk


class PrizeAward(Base):
    __tablename__ = "prize_award"

    id: Mapped[UuidPk]
    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id"))
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.id"))
    spin_id: Mapped[UUID] = mapped_column(ForeignKey("spin.id"), unique=True)
    prize_id: Mapped[UUID] = mapped_column(ForeignKey("prize_catalog.id"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    awarded_at: Mapped[datetime] = mapped_column(Tstz, server_default=text("now()"))
    expires_at: Mapped[datetime] = mapped_column(Tstz)
    redeemed_at: Mapped[datetime | None] = mapped_column(Tstz)
    redeemed_sale_id: Mapped[UUID | None] = mapped_column(ForeignKey("sale.id"))
    redeemed_by: Mapped[UUID | None] = mapped_column(ForeignKey("operator.id"))
    voided_at: Mapped[datetime | None] = mapped_column(Tstz)
