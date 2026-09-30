from datetime import UTC, date, datetime

import pytest

from app.core.time import day_type, end_of_local_day, local_today

TZ = "America/Bogota"


@pytest.mark.parametrize(
    ("local_date", "expected"),
    [
        (date(2026, 10, 4), "sunday"),
        (date(2026, 10, 12), "holiday"),  # Día de la Raza (Monday)
        (date(2027, 3, 26), "holiday"),  # Viernes Santo
        (date(2026, 10, 13), "other"),
        (date(2026, 11, 1), "sunday"),  # Nov 1 moves to Monday Nov 2
        (date(2026, 11, 2), "holiday"),
    ],
)
def test_day_type(local_date, expected):
    assert day_type(local_date) == expected


def test_local_today_uses_business_timezone():
    # 03:00 UTC on Oct 5 is still Oct 4 in Bogotá (UTC-5).
    now = datetime(2026, 10, 5, 3, 0, tzinfo=UTC)
    assert local_today(TZ, now) == date(2026, 10, 4)


def test_end_of_local_day_is_next_local_midnight():
    now = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)  # 15:00 in Bogotá
    assert end_of_local_day(TZ, now) == datetime(2026, 10, 5, 5, 0, tzinfo=UTC)
