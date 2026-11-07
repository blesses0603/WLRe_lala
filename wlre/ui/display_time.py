"""User-facing wall clock; stored observations retain their UTC identities."""
from datetime import datetime, timedelta, timezone

DISPLAY_TIMEZONE = timezone(timedelta(hours=8), 'UTC+8')


def clock_text(timestamp=None):
    value = (datetime.now(DISPLAY_TIMEZONE) if timestamp is None
             else datetime.fromtimestamp(timestamp, DISPLAY_TIMEZONE))
    return value.strftime('%H:%M:%S')
