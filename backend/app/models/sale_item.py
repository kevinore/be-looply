from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPk


class SaleItem(Base):
    __tablename__ = "sale_item"

    id: Mapped[UuidPk]
    sale_id: Mapped[UUID] = mapped_column(ForeignKey("sale.id"))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("product.id"))
    label: Mapped[str] = mapped_column(Text)  # copy of the name at sale time
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_cop: Mapped[int] = mapped_column(Integer)
    unit_cost_cop: Mapped[int | None] = mapped_column(Integer)
    discount_cop: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    prize_award_id: Mapped[UUID | None] = mapped_column(ForeignKey("prize_award.id"))
    created_at: Mapped[CreatedAt]
