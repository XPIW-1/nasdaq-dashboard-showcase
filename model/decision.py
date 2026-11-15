"""Headless version of the dashboard's decision for the daily push (phase 3).

It follows the same gates as app.py's live path: a multiplier is "final" only
when ^NDX (not the QQQ proxy) and VXN are valid, not stale, and the NDX value
matches the end of a validated history. There are no session or saved-history
fallbacks here: a push either has a fresh official reading or reports the
data problem.
"""
import math

from data_sources.ndx import clean_price_series, rolling_high
from model.signals import apply_sentiment_adjustment, calculate_base_multiplier, calculate_drawdown, get_drawdown_zone
from utils.helpers import is_market_data_stale


def _finite_positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _date(value):
    if value is None:
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def _stale(date, now):
    if not date:
        return True
    try:
        return bool(is_market_data_stale(date, now) if now else is_market_data_stale(date))
    except Exception:
        return True


def decide(ndx, vxn, pe=None, now=None):
    ndx = ndx or {}
    vxn = vxn or {}
    pe = pe or {}
    issues = []

    ndx_value = _finite_positive(ndx.get("value"))
    ndx_proxy = bool(ndx.get("proxy"))
    ndx_date = _date(ndx.get("date"))
    ndx_live = ndx_value is not None and not _stale(ndx_date, now)
    if ndx_value is None:
        issues.append("NDX：数据不可用")
    elif not ndx_live:
        issues.append(f"NDX：行情日期已过期（{ndx_date or '未知'}）")
    elif ndx_proxy:
        issues.append("NDX：使用 QQQ 代理数据，不是正式信号")

    vxn_value = _finite_positive(vxn.get("value"))
    vxn_date = _date(vxn.get("date"))
    vxn_live = vxn_value is not None and not _stale(vxn_date, now)
    if vxn_value is None:
        issues.append("VXN：数据不可用")
    elif not vxn_live:
        issues.append(f"VXN：行情日期已过期（{vxn_date or '未知'}）")

    dd = zone = None
    high_info = None
    decidable = False
    if ndx_live:
        try:
            history = clean_price_series(ndx.get("history"), label="NDX")
        except Exception:
            history = None
        consistent = (
            history is not None
            and len(history) > 0
            and math.isclose(float(history.iloc[-1]), ndx_value, rel_tol=1e-9, abs_tol=1e-9)
        )
        if not consistent:
            issues.append("NDX：当前值与历史序列不一致或缺少历史，回撤不可用")
        else:
            high_info = rolling_high(history, len(history))
            if high_info is None or not high_info.get("window_ok"):
                issues.append("NDX：历史窗口不足，回撤不可用")
            else:
                dd = calculate_drawdown(ndx_value, high_info["high"])
                zone = get_drawdown_zone(dd)
                decidable = dd is not None and zone is not None

    if ndx_date and vxn_date and ndx_date != vxn_date and ndx_live and vxn_live:
        issues.append(f"NDX 与 VXN 行情日期不一致（{ndx_date} / {vxn_date}）")

    multiplier = None
    if decidable and not ndx_proxy and vxn_live:
        multiplier = apply_sentiment_adjustment(dd, vxn_value)
        kind = "final" if multiplier is not None else "unavailable"
    elif decidable and ndx_proxy:
        kind = "proxy"
        multiplier = apply_sentiment_adjustment(dd, vxn_value if vxn_live else None)
    elif decidable:
        kind = "base_only"
        multiplier = calculate_base_multiplier(dd)
    else:
        kind = "unavailable"

    pe_value = _finite_positive(pe.get("value"))
    pe_live = bool(pe_value is not None and pe.get("usable_for_model", True))

    return {
        "kind": kind,
        "multiplier": multiplier,
        "dd": dd,
        "zone": zone,
        "ndx_value": ndx_value,
        "ndx_date": ndx_date,
        "high": high_info["high"] if high_info else None,
        "vxn_value": vxn_value if vxn_live else None,
        "vxn_live": vxn_live,
        "vxn_date": vxn_date,
        "pe_value": pe_value,
        "pe_live": pe_live,
        "issues": issues,
    }
