from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, Tstz, UuidPk


class Customer(Base):
    __tablename__ = "customer"

    id: Mapped[UuidPk]
    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id"))
    phone: Mapped[str] = mapped_column(Text)
    alias: Mapped[str] = mapped_column(Text)
    consent_at: Mapped[datetime] = mapped_column(Tstz)
    consent_version: Mapped[str] = mapped_column(Text)
    # Reserved for referrals (V2). Do not use.
    referred_by: Mapped[UUID | None] = mapped_column(ForeignKey("customer.id"))
    created_at: Mapped[CreatedAt]
