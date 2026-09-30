from uuid import UUID

from app.schemas.common import Schema


class LoginIn(Schema):
    email: str
    password: str


class OperatorOut(Schema):
    id: UUID
    name: str
    role: str


class OperatorBusinessOut(Schema):
    id: UUID
    name: str
    slug: str
    branding: dict


class OperatorMeOut(Schema):
    operator: OperatorOut
    business: OperatorBusinessOut
