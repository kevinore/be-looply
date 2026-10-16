from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, SmallInteger, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPk


class PrizeCatalog(Base):
    __tablename__ = "prize_catalog"

    id: Mapped[UuidPk]
    business_id: Mapped[UUID] = mapped_column(ForeignKey("business.id"))
    name: Mapped[str] = mapped_column(Text)
    short_label: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    value: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_value_cop: Mapped[int | None] = mapped_column(Integer)
    # R17: only products of this category take the prize; NULL = any category.
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("product_category.id"))
    weight: Mapped[int] = mapped_column(Integer)
    expires_days: Mapped[int] = mapped_column(SmallInteger, server_default=text("90"))
    color: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[CreatedAt]
