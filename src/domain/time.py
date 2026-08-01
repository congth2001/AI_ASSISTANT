from datetime import datetime
from zoneinfo import ZoneInfo


UTC_TIMEZONE = ZoneInfo("UTC")
VIETNAM_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def now_vietnam() -> datetime:
    """Return the current timezone-aware Vietnam time."""
    return datetime.now(VIETNAM_TIMEZONE)


def as_vietnam_time(value: datetime | None) -> datetime | None:
    """Convert a timestamp to Vietnam time; legacy naive values are UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC_TIMEZONE)
    return value.astimezone(VIETNAM_TIMEZONE)

