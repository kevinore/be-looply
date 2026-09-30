from datetime import datetime
from typing import Annotated
from uuid import UUID

from sqlalchemy import DateTime, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    pass


# Mirrors `uuid PRIMARY KEY DEFAULT gen_random_uuid()`.
UuidPk = Annotated[
    UUID,
    mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    ),
]
# Mirrors `timestamptz NOT NULL DEFAULT now()`.
CreatedAt = Annotated[
    datetime, mapped_column(DateTime(timezone=True), server_default=text("now()"))
]
Tstz = DateTime(timezone=True)
