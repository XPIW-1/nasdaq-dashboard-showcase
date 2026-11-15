"""A-share trading days (Shanghai): weekdays that are not public holidays.

Weekend make-up workdays are not trading days, so the weekday test comes
first. ``chinese_calendar`` ships each year's holiday schedule; when a year is
not covered yet we treat weekdays as trading days and say so.
"""
import datetime as dt

try:
    import chinese_calendar
except ImportError:  # pragma: no cover - installed in the push workflow
    chinese_calendar = None


def is_trading_day(day):
    """Return (is_trading_day, note)."""
    if day.weekday() >= 5:
        return False, None
    if chinese_calendar is None:
        return True, "未安装 chinesecalendar，按工作日处理"
    try:
        return (not chinese_calendar.is_holiday(day)), None
    except NotImplementedError:
        return True, f"交易日历未覆盖 {day.year} 年，按工作日处理；请升级 chinesecalendar"


def previous_trading_day(day, limit=20):
    cursor = day
    for _ in range(limit):
        cursor -= dt.timedelta(days=1)
        if is_trading_day(cursor)[0]:
            return cursor
    return None
