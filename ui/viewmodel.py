"""Pure helpers that turn the dashboard's decision state into display data.

Nothing here decides a multiplier: the model in ``model.signals`` does. These
functions only describe the already-computed decision for the designed UI.
"""
import math

from config import AMMO_RESERVE_DD, DEEP_CHECKPOINTS, DRAWDOWN_ZONES, PE_HIGH, PE_LOW

# Mirrors model.signals.apply_sentiment_adjustment; a unit test keeps the two
# in sync so the ladder can never describe a rule the model does not apply.
VXN_UPGRADES = {
    "mild": (30.0, 1.5),
    "moderate": (35.0, 2.0),
    "deep": (40.0, 2.5),
    "extreme": (45.0, 3.0),
}

# Drawdown scale shown on the ladder (fraction, negative). The ruler is linear
# down to LADDER_LINEAR_DD over the first LADDER_SPLIT of its length; the deep
# end down to LADDER_FLOOR (ammo reserve and manual checkpoints) is compressed
# into the rest. Values beyond the floor pin the cursor to the end.
LADDER_LINEAR_DD = -0.35
LADDER_SPLIT = 0.85
LADDER_FLOOR = -0.55
LADDER_MARKS = (AMMO_RESERVE_DD, *DEEP_CHECKPOINTS)

TIER_KEYS = {1.0: "100", 1.25: "125", 1.5: "150", 2.0: "200", 2.5: "250", 3.0: "300"}


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def zone_range_label(zone):
    if zone["key"] == "normal":
        return "0%～-8%"
    if zone["key"] == "extreme":
        return "≤ -25%"
    return f"-{abs(zone['max_dd']) * 100:.0f}%～-{abs(zone['min_dd']) * 100:.0f}%"


def tier_key(multiplier):
    value = _finite(multiplier)
    if value is None:
        return None
    return TIER_KEYS.get(round(value, 2))


def price_drop_to(dd, threshold):
    """Index move needed to bring drawdown ``dd`` to ``threshold`` (both negative)."""
    dd = _finite(dd)
    threshold = _finite(threshold)
    if dd is None or threshold is None or dd <= -1.0:
        return None
    return (1.0 + threshold) / (1.0 + dd) - 1.0


def build_reason(decision_kind, dd, zone, vxn_value, vxn_live):
    if decision_kind in ("reference_only", "unavailable") or zone is None or dd is None:
        return "关键数据不完整，今天不生成倍数。原因见页面底部的数据健康面板。"
    pct = f"{dd * 100:.1f}%"
    head = f"回撤 {pct}，处于 {zone_range_label(zone)} {zone['label']}档"
    if decision_kind == "proxy":
        tail = "；NDX 使用 QQQ 代理推算，仅作参考，不是正式信号。"
    elif decision_kind == "base_only" or not vxn_live or vxn_value is None:
        tail = "；VXN 不可用，只给出回撤基础倍数，无法确认是否上调。"
    elif zone["key"] == "normal":
        tail = "，此档 VXN 不参与上调。"
    else:
        threshold, _up = VXN_UPGRADES[zone["key"]]
        if vxn_value > threshold:
            tail = f"；VXN {vxn_value:.1f} 已超过 {threshold:.0f}，上调一档。"
        else:
            tail = f"；VXN {vxn_value:.1f} 未达 {threshold:.0f}，不上调。"
    return head + tail


def build_next_steps(decision_kind, dd, zone, vxn_value, vxn_live):
    """Return short lines describing what would move the reading to the next tier."""
    if decision_kind in ("reference_only", "unavailable") or zone is None or dd is None:
        return []
    lines = []
    if zone["key"] in VXN_UPGRADES and vxn_live and vxn_value is not None:
        threshold, upgraded = VXN_UPGRADES[zone["key"]]
        if vxn_value <= threshold:
            gap = max(threshold - vxn_value, 0.0)
            lines.append(f"VXN 再升 {gap:.1f} 点（超过 {threshold:.0f}）→ 上调到 {upgraded:.2f}×")
    index = next(i for i, item in enumerate(DRAWDOWN_ZONES) if item["key"] == zone["key"])
    if index < len(DRAWDOWN_ZONES) - 1:
        nxt = DRAWDOWN_ZONES[index + 1]
        drop = price_drop_to(dd, nxt["max_dd"])
        if drop is not None:
            lines.append(
                f"指数再跌 {abs(drop) * 100:.1f}%（回撤到 {nxt['max_dd'] * 100:.0f}%）"
                f"→ 进入 {nxt['base']:.2f}× 档"
            )
    else:
        levels = sorted(LADDER_MARKS, reverse=True)
        nxt = next((level for level in levels if level < dd - 1e-12), None)
        if nxt is None:
            lines.append(f"已越过 {levels[-1] * 100:.0f}%，倍数维持最高档。")
        else:
            drop = price_drop_to(dd, nxt)
            what = (
                "进入弹药保留区，倍数仍为最高档"
                if math.isclose(nxt, AMMO_RESERVE_DD)
                else "新档位，可手动补仓一次"
            )
            if drop is not None:
                lines.append(f"指数再跌 {abs(drop) * 100:.1f}%（回撤到 {nxt * 100:.0f}%）→ {what}")
    return lines


def build_pe_hint(pe_value, pe_live):
    value = _finite(pe_value)
    if not pe_live or value is None:
        return None
    if value >= PE_HIGH:
        return {
            "level": "warn",
            "text": f"估值偏高（PE {value:.1f}）：按规则照常定投，不额外加码，也不要动用应急资金。",
        }
    if value <= PE_LOW:
        return {"level": "ok", "text": f"估值处于相对低位（PE {value:.1f}）。"}
    return None


def previous_multiplier(history, today):
    """Latest saved final multiplier from a day before ``today``; None if unknown."""
    if history is None or getattr(history, "empty", True):
        return None
    if "multiplier" not in history.columns or "date" not in history.columns:
        return None
    try:
        import pandas as pd

        frame = history[["date", "multiplier"]].copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
        frame["multiplier"] = pd.to_numeric(frame["multiplier"], errors="coerce")
        frame = frame.dropna()
        frame = frame[frame["date"] < pd.Timestamp(today).date()]
        if frame.empty:
            return None
        value = float(frame.sort_values("date").iloc[-1]["multiplier"])
        return value if value in TIER_KEYS else None
    except Exception:
        return None


def tier_since(records, current, today):
    """When the current multiplier started, from dated records before ``today``.

    ``records`` is an iterable of (date, multiplier). Returns None when there
    is no usable record, else {"since", "days", "previous", "changed_today"}.
    """
    import datetime as dt

    import pandas as pd

    current = _finite(current)
    if current is None:
        return None
    today = pd.Timestamp(today).date()
    rows = {}
    for day, value in records or []:
        try:
            day = pd.Timestamp(day).date()
        except Exception:
            continue
        value = _finite(value)
        if value is None or value not in TIER_KEYS or day >= today:
            continue
        rows[day] = value  # later sources win for the same day
    if not rows:
        return None
    ordered = sorted(rows.items())
    if not math.isclose(ordered[-1][1], current):
        return {"since": today, "days": 0, "previous": ordered[-1][1], "changed_today": True}
    since, previous = ordered[-1][0], None
    for day, value in reversed(ordered):
        if math.isclose(value, current):
            since = day
        else:
            previous = value
            break
    days = (today - since).days if isinstance(since, dt.date) else None
    return {"since": since, "days": days, "previous": previous, "changed_today": False}


def tier_change(current, previous):
    current = _finite(current)
    previous = _finite(previous)
    if current is None or previous is None or math.isclose(current, previous):
        return None
    return "up" if current > previous else "down"


def ladder_scale(dd):
    """Map a drawdown to 0..1 along the ruler (piecewise linear, clamped)."""
    if dd >= LADDER_LINEAR_DD:
        return min(max(dd / LADDER_LINEAR_DD, 0.0), 1.0) * LADDER_SPLIT
    deep = (dd - LADDER_LINEAR_DD) / (LADDER_FLOOR - LADDER_LINEAR_DD)
    return LADDER_SPLIT + min(max(deep, 0.0), 1.0) * (1.0 - LADDER_SPLIT)


def ladder_position(dd):
    """0 at the top of the ruler (no drawdown) and 1 at LADDER_FLOOR."""
    value = _finite(dd)
    if value is None:
        return None
    return ladder_scale(value)


def ladder_segments(current_zone_key):
    segments = []
    for zone in DRAWDOWN_ZONES:
        top = zone["max_dd"]
        bottom = max(zone["min_dd"], LADDER_FLOOR)
        upgrade = VXN_UPGRADES.get(zone["key"])
        segments.append(
            {
                "key": zone["key"],
                "label": zone["label"],
                "range": zone_range_label(zone),
                "base": zone["base"],
                "tier": TIER_KEYS[zone["base"]],
                "top": top,
                "start": ladder_scale(top),
                "end": ladder_scale(bottom),
                "upgrade": upgrade,
                "current": zone["key"] == current_zone_key,
            }
        )
    return segments


def percentile_of(value, history):
    value = _finite(value)
    if value is None or history is None:
        return None
    try:
        import pandas as pd

        series = pd.to_numeric(pd.Series(history), errors="coerce").dropna()
        if len(series) < 20:
            return None
        return float((series <= value).mean())
    except Exception:
        return None
