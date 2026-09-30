import re

from app.core.errors import AppError

_NON_DIGITS = re.compile(r"\D")


def normalize_phone(raw: str) -> str:
    """Colombian mobile number as +57 followed by 10 digits starting with 3."""
    digits = _NON_DIGITS.sub("", raw or "")
    if len(digits) == 12 and digits.startswith("57"):
        digits = digits[2:]
    if len(digits) != 10 or not digits.startswith("3"):
        raise AppError("invalid_phone", 422)
    return "+57" + digits
