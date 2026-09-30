from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.holidays import COLOMBIA_HOLIDAYS


def now_utc() -> datetime:
    return datetime.now(UTC)


def local_today(tz: str, now: datetime | None = None) -> date:
    """Today's date in the business time zone."""
    return (now or now_utc()).astimezone(ZoneInfo(tz)).date()


def end_of_local_day(tz: str, now: datetime | None = None) -> datetime:
    """Next local midnight in the business time zone, as a UTC timestamp (R7)."""
    zone = ZoneInfo(tz)
    tomorrow = local_today(tz, now) + timedelta(days=1)
    return datetime.combine(tomorrow, time.min, tzinfo=zone).astimezone(UTC)


def day_type(local_date: date) -> str:
    if local_date.weekday() == 6:
        return "sunday"
    if local_date in COLOMBIA_HOLIDAYS:
        return "holiday"
    return "other"
