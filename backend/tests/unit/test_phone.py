import pytest

from app.core.errors import AppError
from app.core.phone import normalize_phone


@pytest.mark.parametrize(
    "raw", ["310 123 4567", "3101234567", "+57 310-123-4567", "573101234567"]
)
def test_valid_phones(raw):
    assert normalize_phone(raw) == "+573101234567"


@pytest.mark.parametrize("raw", ["6011234567", "31012345", ""])
def test_invalid_phones(raw):
    with pytest.raises(AppError) as exc:
        normalize_phone(raw)
    assert exc.value.code == "invalid_phone"
    assert exc.value.status == 422
