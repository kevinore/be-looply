from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPk


class ProductCategory(Base):
    """Section of the sale screen (e.g. "Bebidas", "Helados")."""

    __tablename__ = "product_category"

    id: Mapped[UuidPk]
    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id"))
    name: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[CreatedAt]


class Product(Base):
    __tablename__ = "product"

    id: Mapped[UuidPk]
    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id"))
    name: Mapped[str] = mapped_column(Text)
    price_cop: Mapped[int] = mapped_column(Integer)
    cost_cop: Mapped[int | None] = mapped_column(Integer)
    photo_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("product_category.id"))
    # R8: a sale earns a stamp only with at least one of these. R17: prizes only here.
    earns_stamp: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    prize_eligible: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[CreatedAt]
