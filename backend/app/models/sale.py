from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Tstz, UuidPk


class Sale(Base):
    __tablename__ = "sale"

    id: Mapped[UuidPk]
    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id"))
    workday_id: Mapped[UUID] = mapped_column(ForeignKey("workday.id"))
    operator_id: Mapped[UUID] = mapped_column(ForeignKey("operator.id"))
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customer.id"))
    status: Mapped[str] = mapped_column(Text)
    payment_method: Mapped[str] = mapped_column(Text)
    total_cop: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True)
    claim_token: Mapped[str] = mapped_column(Text, unique=True)
    claim_expires_at: Mapped[datetime] = mapped_column(Tstz)
    claim_method: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime] = mapped_column(Tstz, server_default=text("now()"))
    claimed_at: Mapped[datetime | None] = mapped_column(Tstz)
    voided_at: Mapped[datetime | None] = mapped_column(Tstz)
    voided_by: Mapped[UUID | None] = mapped_column(ForeignKey("operator.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)
