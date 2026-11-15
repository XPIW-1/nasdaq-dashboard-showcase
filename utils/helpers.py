from datetime import date, datetime, timezone, time
from zoneinfo import ZoneInfo
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

NY = ZoneInfo("America/New_York")

def _parse_data_date(value):
    """Parse adapter dates without treating a valid display-formatted date as stale."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    raise ValueError(f"Unsupported date format: {value}")

def _us_holidays(start, end):
    holidays = set(USFederalHolidayCalendar().holidays(start=start, end=end).date)
    # US equity markets are also closed on Good Friday (not a federal holiday).
    for year in range(start.year, end.year + 1):
        easter = pd.Timestamp(f"{year}-04-01") + pd.offsets.Easter()
        holidays.add((easter - pd.Timedelta(days=2)).date())
    return holidays

def is_market_data_stale(data_date, current_time=None, market="US"):
    """Return stale only when data misses more than one expected US session.

    ``current_time`` may be timezone-aware; naive values are treated as UTC.
    Before the 16:00 New York close, today's session is not yet expected.
    """
    if not data_date: return True
    try:
        data_day = _parse_data_date(data_date)
        now = current_time or datetime.now(timezone.utc)
        if now.tzinfo is None: now = now.replace(tzinfo=timezone.utc)
        local = now.astimezone(NY)
        end = local.date()
        if local.time() < time(16, 0): end = end - pd.Timedelta(days=1)
        start = min(data_day, end) - pd.Timedelta(days=7)
        holidays = _us_holidays(start, end)
        sessions = [x.date() for x in pd.bdate_range(start, end) if x.date() not in holidays]
        if data_day >= end or data_day not in sessions and data_day > end: return False
        missed = sum(day > data_day for day in sessions)
        return missed > 1
    except Exception:
        return True

def stale(date_str, days=2, market=None, current_time=None):
    """Backward-compatible stale helper; market calendar is opt-in."""
    if market == "US": return is_market_data_stale(date_str, current_time=current_time, market=market)
    if not date_str: return True
    try:
        now = current_time or datetime.now(timezone.utc)
        current_day = now.date() if isinstance(now, datetime) else now
        return (current_day-_parse_data_date(date_str)).days > days
    except:return True
