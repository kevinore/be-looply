from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, SmallInteger, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPk


class OptionGroup(Base):
    """A choice a product needs at sale time (e.g. "Base"), shared across products."""

    __tablename__ = "option_group"

    id: Mapped[UuidPk]
    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id"))
    name: Mapped[str] = mapped_column(Text)
    min_select: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    max_select: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[CreatedAt]


class OptionChoice(Base):
    __tablename__ = "option_choice"

    id: Mapped[UuidPk]
    group_id: Mapped[UUID] = mapped_column(ForeignKey("option_group.id"))
    name: Mapped[str] = mapped_column(Text)
    price_delta_cop: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[CreatedAt]


class ProductOptionGroup(Base):
    __tablename__ = "product_option_group"

    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"), primary_key=True)
    group_id: Mapped[UUID] = mapped_column(
        ForeignKey("option_group.id"), primary_key=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class SaleItemOption(Base):
    """Copy of a chosen option at sale time (names and price never change after)."""

    __tablename__ = "sale_item_option"

    id: Mapped[UuidPk]
    sale_item_id: Mapped[UUID] = mapped_column(ForeignKey("sale_item.id"))
    option_id: Mapped[UUID] = mapped_column(ForeignKey("option_choice.id"))
    group_name: Mapped[str] = mapped_column(Text)
    option_name: Mapped[str] = mapped_column(Text)
    price_delta_cop: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[CreatedAt]
