from uuid import UUID

from app.schemas.common import Schema


class OptionChoiceOut(Schema):
    id: UUID
    name: str
    price_delta_cop: int


class OptionGroupOut(Schema):
    """Choose between min_select and max_select options (e.g. "Base": 1 of 2)."""

    id: UUID
    name: str
    min_select: int
    max_select: int
    options: list[OptionChoiceOut]


class ProductOut(Schema):
    id: UUID
    name: str
    price_cop: int
    photo_url: str | None
    description: str | None
    # Section of the sale screen (e.g. "Bebidas"); null = no category.
    category: str | None
    category_id: UUID | None
    # R17: prizes apply only to these products (and only to the prizes of their
    # category, when the prize has one).
    prize_eligible: bool
    option_groups: list[OptionGroupOut]
