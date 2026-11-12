"""How capture dates and times are written, following the clock format chosen in Settings."""

from datetime import datetime

TIME_12_HOUR = "12h"
TIME_24_HOUR = "24h"
TIME_FORMATS = {TIME_12_HOUR, TIME_24_HOUR}
DEFAULT_TIME_FORMAT = TIME_12_HOUR


def format_time(value: datetime, time_format: str = DEFAULT_TIME_FORMAT, seconds: bool = False) -> str:
    """"2:05 PM" or "14:05". AM/PM is spelled out because strftime's %p is empty in some locales."""
    tail = f"{value:%M:%S}" if seconds else f"{value:%M}"
    if time_format == TIME_24_HOUR:
        return f"{value:%H}:{tail}"
    return f"{value.hour % 12 or 12}:{tail} {'AM' if value.hour < 12 else 'PM'}"


def format_capture(value: datetime, time_format: str = DEFAULT_TIME_FORMAT) -> str:
    return f"{value:%B} {value.day}, {value:%Y}  •  {format_time(value, time_format)}"
