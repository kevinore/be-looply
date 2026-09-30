from uuid import UUID

from app.schemas.common import Schema


class ProductOut(Schema):
    id: UUID
    name: str
    price_cop: int
    photo_url: str | None
