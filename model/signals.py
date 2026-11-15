import math

from config import DRAWDOWN_ZONES

ALLOWED_MULTIPLIERS = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0)


def _finite_number(value):
    """Return a finite float or None; never leak NaN/inf into the model."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def multiplier(score,bands):
    if score is None:return None
    r=bands[0][1]
    for t,m in bands:
        if score>=t:r=m
    return r
def market_state(dd):
    x=abs(dd or 0)*100
    return "ATH附近" if x<5 else "正常回调" if x<10 else "明显回调" if x<20 else "技术性熊市" if x<=30 else "深度熊市"
def signal(score,dd):
    if score is not None and score>80 and dd is not None and abs(dd)>.20:return "极端市场机会区间"
    if score is not None and score>70 and dd is not None and abs(dd)>.10:return "较强加仓信号"
    return "维持基础定投"
def extra_buy(score):
    if score is None:return None
    if score < 55:return 0.0
    if score < 65:return 0.25
    if score < 75:return 0.50
    if score < 85:return 1.00
    return 1.50
def action_text(score):
    if score is None:return "数据不足，维持基础定投，不提供额外加仓信号"
    return "维持基础定投，暂不额外加仓" if score<55 else "轻度加仓" if score<65 else "中度加仓" if score<75 else "明显加仓" if score<85 else "重度加仓"


def calculate_drawdown(current, recent_high):
    """Return current / rolling high - 1, or None when inputs are invalid.

    A high that is below the current price cannot be the high of a window that
    contains the current observation, so that case is treated as a data
    mismatch instead of being coerced into a drawdown.
    """
    current_value = _finite_number(current)
    high_value = _finite_number(recent_high)
    if current_value is None or high_value is None:
        return None
    if current_value <= 0 or high_value <= 0:
        return None
    if current_value > high_value * (1.0 + 1e-9):
        return None
    return current_value / high_value - 1.0


def get_drawdown_zone(drawdown):
    """Return the configured zone; invalid drawdowns are never extreme."""
    value = _finite_number(drawdown)
    if value is None:
        return None
    # A positive drawdown means the "high" does not include the current price.
    # A drawdown below -100% is impossible for strictly positive prices.
    if value > 1e-9 or value < -1.0:
        return None
    for zone in reversed(DRAWDOWN_ZONES):
        if value <= zone["max_dd"]:
            return zone
    return DRAWDOWN_ZONES[0]


def calculate_base_multiplier(drawdown):
    zone = get_drawdown_zone(drawdown)
    return zone["base"] if zone else None


def apply_sentiment_adjustment(drawdown, vxn=None):
    """回撤决定基础倍数；只有 Nasdaq-100 VXN 可触发上调。"""
    zone = get_drawdown_zone(drawdown)
    if not zone:
        return None
    vxn_value = _finite_number(vxn)
    if vxn is not None and (vxn_value is None or vxn_value <= 0):
        return None
    if zone["key"] == "normal":
        result = 1.0
    elif zone["key"] == "mild":
        result = 1.5 if vxn_value is not None and vxn_value > 30 else 1.25
    elif zone["key"] == "moderate":
        result = 2.0 if vxn_value is not None and vxn_value > 35 else 1.5
    elif zone["key"] == "deep":
        result = 2.5 if vxn_value is not None and vxn_value > 40 else 2.0
    else:
        result = 3.0 if vxn_value is not None and vxn_value > 45 else 2.5
    return min(ALLOWED_MULTIPLIERS, key=lambda x: abs(x - result))


def sentiment_level(vxn=None):
    value = _finite_number(vxn)
    if value is None or value <= 0:
        return None
    if value > 45:
        return 4
    if value > 40:
        return 3
    if value > 35:
        return 2
    if value > 30:
        return 1
    return 0


def generate_market_summary(drawdown, vxn, multiplier, *, vxn_valid=None,
                            base_multiplier=None, data_note=None, final=True):
    """Describe the current decision without inventing numbers from bad data.

    ``vxn_valid=False`` distinguishes "VXN returned an unusable value" from
    "VXN was simply not supplied"; in that case only the drawdown base
    multiplier is reported and the final multiplier is explicitly unavailable.
    """
    zone = get_drawdown_zone(drawdown)
    note_suffix = f" {data_note}" if data_note else ""
    if zone is None:
        return "关键数据暂不可用（回撤数据不足或无效），暂不生成定投建议。" + note_suffix

    value = _finite_number(drawdown)
    if value is None:
        return "关键数据暂不可用（回撤数据不足或无效），暂不生成定投建议。" + note_suffix

    pct = abs(value) * 100
    base = _finite_number(base_multiplier)
    if base is None or base <= 0:
        base = zone["base"]

    vxn_value = _finite_number(vxn)
    sentiment_available = vxn_valid is not False and vxn_value is not None and vxn_value > 0
    multiplier_value = _finite_number(multiplier)

    if not sentiment_available:
        return (
            f"当前 Nasdaq-100 距近252个交易日最高收盘价回撤 {pct:.1f}%，属于{zone['label']}区间。"
            "VXN 数据无效或不可用，情绪调整不可用；"
            f"回撤基础倍数为 {base:.2f}×，最终建议倍数暂不可用。"
        ) + note_suffix

    if multiplier_value is None or multiplier_value <= 0:
        return "关键数据暂不可用（倍数无法计算），暂不生成定投建议。" + note_suffix

    if multiplier_value > zone["base"]:
        mood = "VXN 已满足当前回撤档位的升档条件"
    else:
        mood = "VXN 尚未满足当前回撤档位的升档条件"

    action = (
        f"建议按 {multiplier_value:.2f}× 定投尺度执行。"
        if final
        else f"仅为参考：{multiplier_value:.2f}× 定投尺度。"
    )
    return (
        f"当前 Nasdaq-100 距近252个交易日最高收盘价回撤 {pct:.1f}%，"
        f"属于{zone['label']}区间。{mood}，{action}"
    ) + note_suffix


def get_next_trigger(drawdown):
    value = _finite_number(drawdown)
    zone = get_drawdown_zone(value)
    if not zone or value is None:
        return None
    idx = DRAWDOWN_ZONES.index(zone)
    if idx == len(DRAWDOWN_ZONES) - 1:
        threshold = None
        next_label = "极端回撤区间上限"
        condition_key = "extreme"
    else:
        next_zone = DRAWDOWN_ZONES[idx + 1]
        threshold = next_zone["max_dd"]
        next_label = f"{next_zone['base']:.2f}×{next_zone['label']}"
        condition_key = next_zone["key"]
    distance = None if threshold is None else max(0.0, abs(threshold) - abs(value))
    return {"current_zone": zone, "next_threshold": threshold, "distance": distance, "next_label": next_label,
            "sentiment_condition": "VXN > 30" if condition_key == "mild" else "VXN > 35" if condition_key == "moderate" else "VXN > 40" if condition_key == "deep" else "VXN > 45"}
