import datetime as dt
import hashlib
import math
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from data_sources.fear_greed import fetch_fear_greed
from data_sources.ndx import clean_price_series, fetch_ndx, rolling_high
from data_sources.valuation import fetch_pe, manual_pe
from data_sources.vxn import fetch_vxn
from model.scoring import (
    fallback_vxn,
    percentile_score,
    score_drawdown,
    score_pe,
)
from model.signals import (
    apply_sentiment_adjustment,
    calculate_base_multiplier,
    calculate_drawdown,
    generate_market_summary,
    get_drawdown_zone,
    get_next_trigger,
    sentiment_level,
)
from utils.helpers import is_market_data_stale
from utils.storage import load_history_preferred, migrate_local_csv, save_history
from utils import access, settings_store
from model import allocation as alloc_model
from config import MODEL_VERSION
from ui import charts as ui_charts
from ui import render as ui
from ui import viewmodel as vm
from ui.theme import global_style

st.set_page_config(
    page_title="NDX-100 定投读数",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(global_style(), unsafe_allow_html=True)
# Sections are laid out in reading order up front; the decision is computed
# below and each slot is filled afterwards. The data-health panel (with the
# emergency manual override) always sits last.
top_slot = st.container()
readout_slot = st.container()
topup_slot = st.container()
ladder_slot = st.container()
groups_slot = st.container()
charts_slot = st.container()
LOCAL_TZ = ZoneInfo("Asia/Taipei")


def local_today():
    return dt.datetime.now(LOCAL_TZ).date().isoformat()

STATE_LABELS = {
    "ok": "正常有效数据",
    "proxy": "QQQ 代理数据",
    "session_fallback": "会话缓存回退",
    "history_fallback": "历史数据回退",
    "stale": "数据过期",
    "invalid": "数据无效",
    "unavailable": "数据不可用",
    "manual": "手动覆盖",
}
DEFAULT_STATE_NOTES = {
    "ok": "指标已通过有效性校验。",
    "proxy": "QQQ 代理数据，不是官方 ^NDX 指数数据。",
    "session_fallback": "仅展示会话中最近一次有效值，不驱动最终倍数。",
    "history_fallback": "仅展示历史保存记录中的有效值，不驱动最终倍数。",
    "stale": "行情日期已过期，仅展示，不驱动最终倍数。",
    "invalid": "数据源返回了非有限、非正值或其他异常数值，已拒绝。",
    "unavailable": "数据源不可用，且没有可用的有效回退数据。",
    "manual": "用户手动覆盖值。",
}


# Decisions use the previous US close, so data is cached for an hour and
# refreshed on demand; there is no auto-refresh.
@st.cache_data(ttl=3600, show_spinner=False)
def market_data():
    return fetch_ndx("max"), fetch_vxn("10y")


@st.cache_data(ttl=43200, show_spinner=False)
def pe_data():
    return fetch_pe()


@st.cache_data(ttl=3600, show_spinner=False)
def fgi_data():
    return fetch_fear_greed()


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _format_date(value, missing="—"):
    """Format a display date as YYYY-MM-DD without inventing a replacement date."""
    if value is None:
        return missing
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return missing
    if not isinstance(parsed, pd.Timestamp) or pd.isna(parsed):
        return missing
    return parsed.date().isoformat()


def _format_fetch_time(value):
    """Format a local fetch timestamp in Beijing time; never invent a timestamp."""
    if value is None:
        return "暂无数据"
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
    except Exception:
        return "暂无数据"
    if not isinstance(parsed, pd.Timestamp) or pd.isna(parsed):
        return "暂无数据"
    try:
        local = parsed.tz_convert("Asia/Taipei")
    except Exception:
        return "暂无数据"
    return local.strftime("%Y-%m-%d %H:%M:%S") + "（台北时间）"


def _format_score(value):
    number = _finite_number(value)
    return "暂无数据" if number is None else f"{number:.1f}"


def valid_indicator_value(key, value):
    """Apply per-indicator validity rules instead of one blanket >0 rule."""
    number = _finite_number(value)
    if number is None:
        return None
    if key in ("ndx", "vxn", "pe"):
        return number if number > 0 else None
    if key in ("fgi", "breadth", "score"):
        return number if 0.0 <= number <= 100.0 else None
    return number


DISPLAYABLE_DATE_STATES = {
    "ok",
    "proxy",
    "session_fallback",
    "history_fallback",
    "stale",
}


def _display_market_date(item):
    """Return a real, displayable market date; never invent or compare a missing one."""
    if item is None or item.get("value") is None:
        return None
    # Manual input dates are entry dates, not source market dates.
    if item.get("input_mode") == "manual":
        return None
    if item.get("data_state") not in DISPLAYABLE_DATE_STATES:
        return None
    raw_date = item.get("date")
    if raw_date is None:
        return None
    try:
        parsed = pd.to_datetime(raw_date, errors="coerce")
    except Exception:
        return None
    if not isinstance(parsed, pd.Timestamp) or pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def session_fallback(key, item):
    """Cache only valid values; invalid input must never overwrite the cache."""
    cache_key = f"last_valid_{key}"
    item = dict(item or {})
    had_value = item.get("value") is not None
    valid_value = valid_indicator_value(key, item.get("value"))
    if valid_value is not None:
        item["value"] = valid_value
        item["fallback"] = False
        item.pop("fallback_kind", None)
        item["data_state"] = "proxy" if item.get("proxy") else "ok"
        st.session_state[cache_key] = {
            **item,
            "_cached_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        return item

    item["value"] = None
    item["data_state"] = (
        "invalid"
        if had_value or item.get("status") == "invalid"
        else "unavailable"
    )
    item["note"] = item.get("note") or item.get("error") or DEFAULT_STATE_NOTES[item["data_state"]]
    if cache_key in st.session_state:
        saved = dict(st.session_state[cache_key])
        saved_value = valid_indicator_value(key, saved.get("value"))
        if saved_value is not None:
            saved["value"] = saved_value
            saved["source"] = f"最近一次有效数据 · {saved.get('source', '')}"
            saved["fallback"] = True
            saved["fallback_kind"] = "session"
            saved["data_state"] = "session_fallback"
            try:
                saved["stale"] = (
                    bool(is_market_data_stale(saved.get("date")))
                    if saved.get("date")
                    else True
                )
            except Exception:
                saved["stale"] = True
            saved["note"] = (
                "会话缓存回退：仅展示，不驱动最终倍数。"
                if not saved.get("stale")
                else "会话缓存回退且行情日期已过期：仅展示，不驱动最终倍数。"
            )
            return saved
    return item


def _numeric_column(frame, field):
    if frame is None:
        return pd.Series(dtype="float64")
    if field not in frame.columns:
        return pd.Series([float("nan")] * len(frame), index=frame.index, dtype="float64")
    values = pd.to_numeric(frame[field], errors="coerce")
    return values.replace([float("inf"), float("-inf")], float("nan"))


def _date_column(frame, field):
    if frame is None:
        return pd.Series(dtype="datetime64[ns, UTC]")
    if field not in frame.columns:
        return pd.to_datetime(
            pd.Series([None] * len(frame), index=frame.index),
            errors="coerce",
            utc=True,
        )
    return pd.to_datetime(frame[field], errors="coerce", utc=True)


def ndx_history_fallback(item):
    """Use one saved snapshot only: current NDX and its high come from one row."""
    item = dict(item)
    if item.get("value") is not None:
        return item
    if hist is None or hist.empty or "ndx" not in hist.columns or "ath" not in hist.columns:
        return item

    today = pd.Timestamp.now(tz="America/New_York").date()
    ndx_values = _numeric_column(hist, "ndx")
    ath_values = _numeric_column(hist, "ath")
    ndx_dates = _date_column(hist, "ndx_date")
    ath_dates = _date_column(hist, "ath_date")
    saved_dates = _date_column(hist, "date")

    mask = (
        (ndx_values > 0)
        & (ath_values > 0)
        & ndx_dates.notna()
        & ath_dates.notna()
        & saved_dates.notna()
    )
    if not mask.any():
        return item
    work = pd.DataFrame(
        {
            "ndx": ndx_values[mask],
            "ath": ath_values[mask],
            "ndx_date": ndx_dates[mask],
            "ath_date": ath_dates[mask],
            "saved_at": saved_dates[mask],
        }
    )
    # The high must belong to the same snapshot and must not post-date the
    # market date of the saved current value. Rows whose market date is later
    # than their save date, or later than today, are not valid history.
    work = work[
        (work["ath"] >= work["ndx"])
        & (work["ath_date"].dt.date <= work["ndx_date"].dt.date)
        & (work["ndx_date"].dt.date <= work["saved_at"].dt.date)
        & (work["ndx_date"].dt.date <= today)
    ]
    if work.empty:
        return item
    work = work.sort_values(["ndx_date", "saved_at"], ascending=True, na_position="first")
    row = work.iloc[-1]
    drawdown = calculate_drawdown(float(row["ndx"]), float(row["ath"]))
    if drawdown is None:
        return item

    item["value"] = float(row["ndx"])
    item["date"] = row["ndx_date"].date().isoformat()
    item["saved_at"] = None if pd.isna(row["saved_at"]) else row["saved_at"].date().isoformat()
    item["fallback_high"] = float(row["ath"])
    item["fallback_high_date"] = row["ath_date"].date().isoformat()
    item["fallback"] = True
    item["fallback_kind"] = "history"
    item["data_state"] = "history_fallback"
    try:
        item["stale"] = bool(is_market_data_stale(item["date"]))
    except Exception:
        item["stale"] = True
    item["source"] = f"最近一次有效数据（历史保存） · {item.get('source') or '未知'}"
    stale_prefix = "历史数据已过期。" if item["stale"] else ""
    item["note"] = (
        f"{stale_prefix}历史数据回退：当前值与历史高点来自同一条保存记录；"
        "旧记录未保存代理标识与窗口口径。仅展示，不驱动最终倍数。"
    )
    return item


def vxn_history_fallback(item):
    """Use the latest valid saved VXN row; never apply an upper bound."""
    item = dict(item)
    if item.get("value") is not None:
        return item
    if hist is None or hist.empty or "vxn" not in hist.columns:
        return item

    today = pd.Timestamp.now(tz="America/New_York").date()
    vxn_values = _numeric_column(hist, "vxn")
    vxn_dates = _date_column(hist, "vxn_date")
    saved_dates = _date_column(hist, "date")
    mask = (vxn_values > 0) & vxn_dates.notna() & saved_dates.notna()
    if not mask.any():
        return item
    work = pd.DataFrame(
        {
            "vxn": vxn_values[mask],
            "vxn_date": vxn_dates[mask],
            "saved_at": saved_dates[mask],
        }
    )
    # A saved VXN observation cannot post-date its save date or today.
    work = work[
        (work["vxn_date"].dt.date <= work["saved_at"].dt.date)
        & (work["vxn_date"].dt.date <= today)
    ]
    if work.empty:
        return item
    work = work.sort_values(["vxn_date", "saved_at"], ascending=True, na_position="first")
    row = work.iloc[-1]

    item["value"] = float(row["vxn"])
    item["date"] = row["vxn_date"].date().isoformat()
    item["saved_at"] = None if pd.isna(row["saved_at"]) else row["saved_at"].date().isoformat()
    item["fallback"] = True
    item["fallback_kind"] = "history"
    item["data_state"] = "history_fallback"
    try:
        item["stale"] = bool(is_market_data_stale(item["date"]))
    except Exception:
        item["stale"] = True
    item["source"] = f"最近一次有效数据（历史保存） · {item.get('source') or '未知'}"
    stale_prefix = "历史数据已过期。" if item["stale"] else ""
    item["note"] = (
        f"{stale_prefix}历史数据回退：仅展示，不驱动情绪升档或最终倍数。"
    )
    return item


def _mark_live_freshness(item):
    item = dict(item)
    if item.get("value") is None or item.get("data_state") not in ("ok", "proxy"):
        return item
    data_date = item.get("date")
    try:
        is_stale = bool(is_market_data_stale(data_date)) if data_date else True
    except Exception:
        is_stale = True
    item["stale"] = is_stale
    if is_stale:
        item["data_state"] = "stale"
        item["note"] = (
            "QQQ 代理数据已过期：仅展示，不驱动最终倍数。"
            if item.get("proxy")
            else "行情日期已过期：仅展示，不驱动最终倍数。"
        )
    return item


def sanitize_for_save(row):
    """Never persist NaN/inf, non-positive prices, or out-of-range scores."""
    clean = dict(row)
    numeric_fields = (
        "ndx",
        "ath",
        "drawdown",
        "drawdown_score",
        "vxn",
        "vxn_score",
        "pe",
        "pe_score",
        "total_score",
        "confidence",
        "multiplier",
    )
    for field in numeric_fields:
        clean[field] = _finite_number(clean.get(field))
    for field in ("ndx", "ath", "vxn", "pe"):
        if clean[field] is not None and clean[field] <= 0:
            clean[field] = None
    if clean["drawdown"] is not None and not (-1.0 <= clean["drawdown"] <= 0.0):
        clean["drawdown"] = None
    for field in ("drawdown_score", "vxn_score", "pe_score", "total_score", "confidence"):
        if clean[field] is not None and not (0.0 <= clean[field] <= 100.0):
            clean[field] = None
    if clean["ndx"] is None or clean["ath"] is None:
        clean["drawdown"] = None
    if clean["drawdown"] is None:
        clean["drawdown_score"] = None
        clean["multiplier"] = None
    if clean["vxn"] is None:
        clean["vxn_score"] = None
    if clean["pe"] is None:
        clean["pe_score"] = None
    if clean["multiplier"] is not None and clean["multiplier"] not in (1.0, 1.25, 1.5, 2.0, 2.5, 3.0):
        clean["multiplier"] = None
    return clean


def _manual_default(key, item, fallback):
    value = valid_indicator_value(key, item.get("value"))
    return float(value) if value is not None else float(fallback)


manual = bool(st.session_state.get("manual_override", False))

ndx, vxn = market_data()
fgi = fgi_data()
pe = pe_data()
hist, history_backend, history_error = load_history_preferred()

# Resolve fallbacks in order: live value -> session cache -> saved history.
ndx = ndx_history_fallback(session_fallback("ndx", ndx))
vxn = vxn_history_fallback(session_fallback("vxn", vxn))
fgi = session_fallback("fgi", fgi)
pe = session_fallback("pe", pe)

# PE is published as a point-in-time portfolio value. Build its chart history
# from validated dashboard snapshots when the provider does not supply a series.
if pe.get("history") is None and hist is not None and not hist.empty:
    try:
        pe_values = pd.to_numeric(hist.get("pe"), errors="coerce")
        pe_dates = pd.to_datetime(hist.get("date"), errors="coerce")
        pe_series = pd.Series(pe_values.to_numpy(), index=pe_dates).dropna()
        pe_series = pe_series[(pe_series > 0) & pe_series.index.notna()].sort_index()
        if not pe_series.empty:
            pe["history"] = pe_series
    except Exception:
        pass

ndx = _mark_live_freshness(ndx)
vxn = _mark_live_freshness(vxn)

if manual:
    # Widgets live in the data-health panel; read their last values here.
    manual_defaults = {
        "manual_ndx": _manual_default("ndx", ndx, 20000.0),
        "manual_vxn": _manual_default("vxn", vxn, 20.0),
        "manual_fgi": _manual_default("fgi", fgi, 50.0),
        "manual_pe": _manual_default("pe", pe, 25.0),
    }
    manual_ndx = st.session_state.get("manual_ndx", manual_defaults["manual_ndx"])
    manual_vxn = st.session_state.get("manual_vxn", manual_defaults["manual_vxn"])
    manual_fgi = st.session_state.get("manual_fgi", manual_defaults["manual_fgi"])
    manual_pe_value = st.session_state.get("manual_pe", manual_defaults["manual_pe"])

    ndx_value = valid_indicator_value("ndx", manual_ndx)
    ndx = dict(ndx)
    ndx.update(
        {
            "value": ndx_value,
            "date": local_today(),
            "source": "Manual",
            "history": None,
            "data_state": "ok" if ndx_value is not None else "invalid",
            "stale": False,
            "fallback": False,
            "proxy": False,
            "saved_at": None,
            "note": "手动覆盖；未提供可用于回撤校验的历史序列。",
        }
    )
    ndx.pop("fallback_high", None)
    ndx.pop("fallback_high_date", None)

    vxn_value = valid_indicator_value("vxn", manual_vxn)
    vxn = dict(vxn)
    vxn.update(
        {
            "value": vxn_value,
            "date": local_today(),
            "source": "Manual",
            "history": None,
            "data_state": "ok" if vxn_value is not None else "invalid",
            "stale": False,
            "fallback": False,
            "proxy": False,
            "saved_at": None,
            "note": "手动覆盖。",
        }
    )

    fgi_value = valid_indicator_value("fgi", manual_fgi)
    fgi = dict(fgi)
    fgi.update(
        {
            "value": fgi_value,
            "date": local_today(),
            "source": "Manual",
            "data_state": "ok" if fgi_value is not None else "invalid",
            "stale": False,
            "fallback": False,
            "note": "手动覆盖；仅展示。",
        }
    )

    pe = manual_pe(
        manual_pe_value, "Manual", "Nasdaq-100 Index trailing P/E"
    )
    pe["data_state"] = "ok" if pe.get("value") is not None else "invalid"
    pe["stale"] = False
    pe["note"] = "手动覆盖。"

    for item in (ndx, vxn, fgi, pe):
        item["input_mode"] = "manual"

ndx_state = ndx.get("data_state", "unavailable")
vxn_state = vxn.get("data_state", "unavailable")
pe_state = pe.get("data_state", "unavailable")
ndx_live = (
    ndx_state in ("ok", "proxy")
    and not bool(ndx.get("stale"))
    and ndx.get("value") is not None
)
vxn_live = (
    vxn_state == "ok"
    and not bool(vxn.get("stale"))
    and vxn.get("value") is not None
)
pe_live = bool(
    pe_state == "ok"
    and pe.get("value") is not None
    and pe.get("usable_for_model", True)
)

# Rebuild the high from a validated, sorted, de-duplicated series only.
ndx_history = None
history_consistent = False
raw_history = ndx.get("history")
if raw_history is not None:
    try:
        ndx_history = clean_price_series(raw_history, label="NDX")
    except Exception:
        ndx_history = None
if ndx_history is not None:
    if len(ndx_history) == 0:
        ndx_history = None
    elif ndx.get("value") is not None:
        history_consistent = math.isclose(
            float(ndx_history.iloc[-1]),
            float(ndx["value"]),
            rel_tol=1e-9,
            abs_tol=1e-9,
        )

ndx_series_mismatch = bool(
    ndx_live and raw_history is not None and not history_consistent
)
if ndx_series_mismatch:
    ndx["note"] = (
        "当前 NDX 值与历史序列末值不一致，回撤计算已禁用；最终倍数不可用。"
    )

high_info = None
if ndx_history is not None and history_consistent:
    high_info = rolling_high(ndx_history, len(ndx_history))
    if high_info is not None:
        high_info["origin"] = "live_history"
if (
    high_info is None
    and ndx.get("fallback_kind") == "history"
    and ndx.get("fallback_high") is not None
):
    high_info = {
        "high": float(ndx["fallback_high"]),
        "high_date": ndx.get("fallback_high_date"),
        "window": None,
        "window_ok": False,
        "origin": "saved_snapshot",
    }

if (
    high_info is not None
    and high_info.get("origin") == "live_history"
    and not high_info.get("window_ok")
):
    ndx["note"] = (
        f"历史仅 {high_info['window']} 个有效交易日；"
        "回撤仅参考，不驱动最终倍数。"
    )
elif ndx_live and high_info is None and not manual and not ndx_series_mismatch:
    ndx["note"] = "缺少可校验的历史最高收盘价序列；回撤与最终倍数不可用。"

recent_high = high_info["high"] if high_info else None
high_date = high_info["high_date"] if high_info else None
dd = calculate_drawdown(ndx.get("value"), recent_high) if high_info else None
zone = get_drawdown_zone(dd)

high_window_ok = bool(high_info.get("window_ok")) if high_info else False
drawdown_decidable = bool(
    ndx_live
    and dd is not None
    and zone is not None
    and high_info is not None
    and high_info.get("origin") == "live_history"
    and history_consistent
    and high_window_ok
)

base_multiplier = calculate_base_multiplier(dd) if zone else None
final_multiplier = None
proxy_multiplier = None
if drawdown_decidable and ndx_state == "proxy":
    proxy_multiplier = apply_sentiment_adjustment(
        dd, vxn.get("value") if vxn_live else None
    )
    decision_kind = "proxy" if proxy_multiplier is not None else "unavailable"
elif drawdown_decidable and ndx_state == "ok" and vxn_live:
    final_multiplier = apply_sentiment_adjustment(dd, vxn.get("value"))
    decision_kind = "final" if final_multiplier is not None else "base_only"
elif drawdown_decidable:
    decision_kind = "base_only"
elif dd is not None and zone is not None:
    decision_kind = "reference_only"
else:
    decision_kind = "unavailable"

vxn_value = valid_indicator_value("vxn", vxn.get("value"))
vxn_score = None
if vxn_live:
    vxn_score = percentile_score(vxn_value, vxn.get("history"))
    if vxn_score is None:
        vxn_score = fallback_vxn(vxn_value)
pe_value = valid_indicator_value("pe", pe.get("value"))
pe_score = score_pe(pe_value) if pe_live else None
drawdown_score = (
    score_drawdown(dd * 100) if dd is not None and drawdown_decidable else None
)
scores = {"vxn": vxn_score, "pe": pe_score, "drawdown": drawdown_score}
level = sentiment_level(vxn.get("value"))

summary_note = None
if decision_kind == "proxy":
    summary_note = (
        "注意：NDX 使用 QQQ 代理数据推算，以上仅为代理参考，不作为官方指数最终信号。"
    )
summary = generate_market_summary(
    dd if drawdown_decidable else None,
    vxn_value if vxn_live else None,
    final_multiplier if final_multiplier is not None else proxy_multiplier,
    vxn_valid=vxn_live,
    base_multiplier=base_multiplier if drawdown_decidable else None,
    data_note=summary_note,
    final=final_multiplier is not None,
)

# ---------------------------------------------------------------------------
# Designed view (first screen, ladder, indicator groups, charts)
# ---------------------------------------------------------------------------
ndx_market_date = _display_market_date(ndx)
vxn_market_date = _display_market_date(vxn)

issues = []
if manual:
    issues.append("正在使用手动输入的数据，仅供应急，不会写入历史。")
for issue_label, issue_item in (("NDX", ndx), ("VXN", vxn)):
    if issue_item.get("input_mode") == "manual":
        continue
    issue_state = issue_item.get("data_state", "unavailable")
    if issue_state == "ok":
        continue
    issue_text = f"{issue_label}：{STATE_LABELS.get(issue_state, issue_state)}"
    if issue_state in ("session_fallback", "history_fallback", "stale") and issue_item.get("date"):
        issue_text += f"（行情日期 {_format_date(issue_item.get('date'))}）"
    issues.append(issue_text)
if ndx_market_date and vxn_market_date and ndx_market_date != vxn_market_date:
    issues.append(f"NDX 与 VXN 行情日期不一致（{ndx_market_date} / {vxn_market_date}）")
if ndx_series_mismatch:
    issues.append("NDX 当前值与历史序列末值不一致，回撤计算已禁用")

if decision_kind == "final" and not issues:
    fresh = {"level": "ok", "text": f"数据截至 {ndx_market_date or '—'} 美股收盘 · 正常"}
elif decision_kind in ("final", "proxy", "base_only"):
    fresh = {"level": "warn", "text": f"数据截至 {ndx_market_date or '—'} 美股收盘 · 有降级，点此查看"}
else:
    fresh = {"level": "bad", "text": "数据不可用于决策 · 点此查看原因"}

display_multiplier = {
    "final": final_multiplier,
    "proxy": proxy_multiplier,
    "base_only": base_multiplier,
}.get(decision_kind)
kind_label = {
    "final": "正式信号",
    "proxy": "QQQ 代理参考，非正式信号",
    "base_only": "回撤基础倍数 · VXN 不可用",
    "reference_only": "仅参考 · 不生成倍数",
    "unavailable": "暂不可用",
}[decision_kind]
vxn_display_value = vxn_value if vxn_live else None
def _tier_records():
    records = []
    if hist is not None and not getattr(hist, "empty", True) and {"date", "multiplier"} <= set(hist.columns):
        records.extend(zip(hist["date"], hist["multiplier"]))
    try:
        push_state = settings_store.get_push_state()
    except Exception:
        push_state = {}
    if push_state.get("date"):
        records.append((push_state["date"], push_state.get("multiplier")))
    return records


tier_info = vm.tier_since(_tier_records(), final_multiplier, local_today()) if decision_kind == "final" else None
change = (
    vm.tier_change(final_multiplier, tier_info["previous"])
    if tier_info and tier_info["changed_today"]
    else None
)
animate_once = not st.session_state.get("_readout_animated", False)
st.session_state["_readout_animated"] = True

with top_slot:
    bar_left, bar_right = st.columns([6, 1], vertical_alignment="bottom")
    with bar_left:
        st.html(
            ui.top_bar(
                f"US close {ndx_market_date or '—'} · 获取于 {_format_fetch_time(ndx.get('updated_at'))}"
            )
        )
    with bar_right:
        if st.button("刷新数据", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

with readout_slot:
    st.html(
        ui.readout(
            value=display_multiplier,
            kind_label=kind_label,
            reason=vm.build_reason(decision_kind, dd, zone, vxn_display_value, vxn_live),
            next_lines=vm.build_next_steps(decision_kind, dd, zone, vxn_display_value, vxn_live),
            fresh=fresh,
            issues=issues,
            pe_hint=vm.build_pe_hint(pe.get("value"), pe_live),
            change=change,
            animate=animate_once,
        ),
        unsafe_allow_javascript=True,
    )

# ---------------------------------------------------------------------------
# Today's plan (2026-11 plan): per-fund amounts, tier reminder, manual top-up
# and ammo. Money figures stay locked on a public deployment until the access
# code is entered.
# ---------------------------------------------------------------------------
AMMO_STALE_DAYS = 30
try:
    plan_config = alloc_model.load_config()
    funds_error = None
except Exception as exc:  # malformed funds.yaml must not break the reading
    plan_config, funds_error = None, str(exc)


def _flash(key, backend, error, ok_text):
    st.session_state[key] = (
        f"{ok_text}已保存到 {backend}；Supabase 写入失败：{error}" if error else f"{ok_text}已保存到 {backend}。"
    )


with topup_slot:
    if funds_error:
        st.error(f"funds.yaml 读取失败，加仓金额暂不可用：{funds_error}")
    elif not access.is_unlocked():
        st.html(ui.locked("加仓金额和弹药余额属于个人信息，输入访问口令后显示。"))
        with st.form("unlock_form", border=False):
            code_col, button_col = st.columns([3, 1], vertical_alignment="bottom")
            attempt = code_col.text_input("访问口令", type="password", key="access_attempt")
            if button_col.form_submit_button("解锁", use_container_width=True):
                if access.try_unlock(attempt):
                    st.rerun()
                else:
                    st.error("口令不正确。")
    else:
        is_final = decision_kind == "final"
        ammo_record = settings_store.get_ammo()
        ammo_state = ammo_record["state"]
        ammo = alloc_model.ammo_status(dd if is_final else None, final_multiplier, plan_config, ammo_state)
        today_topup = alloc_model.topup_for(ammo, plan_config) if is_final else None
        previous_topup = (
            alloc_model.daily_topup(tier_info["previous"], plan_config)
            if tier_info and tier_info["changed_today"]
            else None
        )
        checkpoint = alloc_model.checkpoint(dd, final_multiplier) if is_final else None
        manual_records = ammo_state.get("manual", {}) if ammo_state else {}
        manual_fund = next((f.label for f in plan_config.funds if f.manual_only), None)
        st.html(
            ui.plan_panel(
                state="final" if is_final else "unavailable",
                topup=today_topup,
                previous_topup=previous_topup,
                auto_funds=plan_config.auto_funds,
                tier_info=tier_info,
                ammo=ammo,
                ammo_name=plan_config.ammo_name,
                ammo_age=settings_store.days_since(ammo_record["updated_at"]),
                stale_days=AMMO_STALE_DAYS,
                checkpoint=checkpoint,
                manual_record=manual_records.get(checkpoint) if checkpoint else None,
                manual_fund=manual_fund,
                last_auto=ammo_state.get("last_auto") if ammo_state else None,
            )
        )
        with st.expander("各档金额 · 更新" + plan_config.ammo_name):
            st.html(
                ui.tier_amounts(
                    alloc_model.tier_table(plan_config),
                    final_multiplier if is_final else None,
                    lambda m: alloc_model.monthly_draw(m, plan_config),
                )
            )
            st.caption(
                f"自动定投固定每日 ¥{plan_config.base:,.0f}，不随倍数变化。"
                f"每日加仓 = {plan_config.base:,.0f} × (倍数 − 1)，四舍五入到整数元，按顺序填进可加仓基金的单日剩余额度。"
                f"每月弹药 = 每日加仓 × {plan_config.trading_days}。"
                "每个交易日推送后，当天的加仓金额自动计入弹药。基金配置在仓库的 funds.yaml 中修改。"
            )
            with st.form("ammo_form", border=False):
                balance_default = ammo_state.get("balance") if ammo_state else None
                new_balance = st.number_input(
                    f"{plan_config.ammo_name}余额（元）",
                    min_value=0.0,
                    step=100.0,
                    value=float(balance_default if balance_default is not None else plan_config.ammo_total),
                )
                used_inputs = {}
                zone_cols = st.columns(len(plan_config.zones)) if plan_config.zones else []
                for col, zone_cfg in zip(zone_cols, plan_config.zones):
                    used_inputs[zone_cfg.key] = col.number_input(
                        f"{zone_cfg.label}已用（额度 ¥{zone_cfg.budget:,.0f}）",
                        min_value=0.0,
                        step=100.0,
                        value=float((ammo_state.get("used") or {}).get(zone_cfg.key, 0.0)) if ammo_state else 0.0,
                    )
                if st.form_submit_button("保存弹药"):
                    backend, save_error = settings_store.set_ammo(
                        new_balance, used_inputs, manual_records, ammo_state.get("last_auto") if ammo_state else None
                    )
                    _flash("_ammo_msg", backend, save_error, "")
                    st.rerun()
            if checkpoint:
                if checkpoint in manual_records:
                    if st.button(f"撤销本档（{checkpoint}）额外补仓记录"):
                        backend, save_error = settings_store.undo_manual(ammo_state, checkpoint)
                        _flash("_ammo_msg", backend, save_error, "已撤销，")
                        st.rerun()
                else:
                    with st.form("manual_form", border=False):
                        amount_col, button_col = st.columns([3, 1], vertical_alignment="bottom")
                        manual_amount = amount_col.number_input(
                            f"本档（{checkpoint}）额外补仓金额（元，从弹药扣除）", min_value=0.0, step=10.0
                        )
                        if button_col.form_submit_button("记录", use_container_width=True):
                            try:
                                backend, save_error = settings_store.record_manual(
                                    ammo_state,
                                    checkpoint,
                                    manual_amount,
                                    ammo["zone"].key if ammo["zone"] else None,
                                    local_today(),
                                )
                                _flash("_ammo_msg", backend, save_error, "额外补仓已记录，")
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))
            if st.session_state.get("_ammo_msg"):
                st.caption(st.session_state.pop("_ammo_msg"))
            st.caption(
                f"弹药存储：{ammo_record['backend']}"
                + (f"（Supabase 读取失败，已回退：{ammo_record['error']}）" if ammo_record["error"] else "")
            )

with ladder_slot:
    st.html(ui.section("档位", "Drawdown ruler"))
    st.html(
        ui.ladder(
            dd=dd,
            position=vm.ladder_position(dd),
            zone_key=zone["key"] if zone else None,
            decidable=decision_kind in ("final", "base_only"),
            vxn_value=valid_indicator_value("vxn", vxn.get("value")),
            vxn_live=vxn_live,
            flash=change is not None and animate_once,
            animate=animate_once,
        )
    )


def _num(value, fmt):
    number = _finite_number(value)
    return "—" if number is None else format(number, fmt)


with groups_slot:
    st.html(ui.section("指标", "Instruments"))
    dd_detail = (
        f'NDX <span class="mono">{_num(ndx.get("value"), ",.2f")}</span>'
        f' · 历史高点 <span class="mono">{_num(recent_high, ",.2f")}</span>'
        f'（{_format_date(high_date)}）'
    )
    if ndx.get("proxy"):
        dd_detail += " · QQQ 代理"
    vxn_pct = vm.percentile_of(vxn.get("value"), vxn.get("history")) if vxn_live else None
    vxn_detail = (
        f'10 年分位 <span class="mono">{vxn_pct * 100:.0f}%</span>'
        if vxn_pct is not None
        else "10 年分位暂无"
    )
    if zone is not None and zone["key"] in vm.VXN_UPGRADES:
        vxn_detail += f' · 本档阈值 <span class="mono">{vm.VXN_UPGRADES[zone["key"]][0]:.0f}</span>'
    if not vxn_live and vxn.get("value") is not None:
        vxn_detail += " · 未用于升档"
    fgi_value = valid_indicator_value("fgi", fgi.get("value"))
    pe_number = valid_indicator_value("pe", pe.get("value"))
    st.html(
        ui.groups(
            [
                ui.gauge("Drawdown", "回撤", "—" if dd is None else f"{dd * 100:.1f}%", dd_detail),
                ui.gauge("VXN", "波动率", _num(vxn.get("value"), ".1f"), vxn_detail),
            ],
            [
                ui.gauge(
                    "F&G",
                    "美股情绪",
                    "—" if fgi_value is None else f"{fgi_value:.0f}",
                    "CNN 恐惧与贪婪<br>0 恐惧 · 100 贪婪",
                ),
                ui.gauge(
                    "P/E",
                    "估值代理",
                    "—" if pe_number is None else f"{pe_number:.1f}",
                    "IQQ ETF 组合代理<br>偏高 ≥35 · 偏低 ≤22",
                ),
            ],
        )
    )


def _series(item, start=None):
    history = item.get("history")
    if history is None:
        return pd.Series(dtype=float)
    try:
        result = history.copy() if isinstance(history, pd.Series) else pd.Series(history)
        if pd.api.types.is_numeric_dtype(result.index):
            return pd.Series(dtype=float)
        converted_index = pd.to_datetime(result.index, errors="coerce", utc=True)
        if converted_index.isna().all():
            return pd.Series(dtype=float)
        result.index = converted_index.tz_convert(None)
        result = pd.to_numeric(result, errors="coerce").dropna().sort_index()
        if start is not None:
            start_key = pd.Timestamp(start)
            if start_key.tzinfo is not None:
                start_key = start_key.tz_convert(None)
            result = result[result.index >= start_key]
        return result
    except Exception:
        return pd.Series(dtype=float)


RANGE_DAYS = {"3个月": 92, "1年": 365, "3年": 1096, "5年": 1827}
chart_frames = None
with charts_slot:
    st.html(ui.section("走势", "Drawdown · VXN"))
    if ndx_history is not None and len(ndx_history):
        range_label = st.segmented_control(
            "图表时间范围",
            ["3个月", "1年", "3年", "5年", "全部"],
            default="1年",
            key="chart_range",
            label_visibility="collapsed",
        ) or "1年"
        price_full = ndx_history.copy()
        price_full.index = pd.to_datetime(price_full.index, errors="coerce", utc=True).tz_convert(None)
        if range_label == "全部":
            start_date = price_full.index.min()
        else:
            start_date = price_full.index.max() - pd.Timedelta(days=RANGE_DAYS[range_label])
        drawdown_full = price_full / price_full.cummax() - 1.0
        price = price_full[price_full.index >= start_date]
        drawdown_series = drawdown_full[drawdown_full.index >= start_date]
        vxn_series = _series(vxn, start_date)
        fgi_series = _series(fgi, start_date)
        pe_series = _series(pe, start_date)
        if pe_series.empty and pe.get("value") is not None and pe.get("date"):
            pe_series = pd.Series([float(pe["value"])], index=pd.to_datetime([pe["date"]]), name="PE")
        components.html(
            ui_charts.chart_html(
                [ui_charts.drawdown_panel(drawdown_series), ui_charts.vxn_panel(vxn_series)], 480
            ),
            height=490,
        )
        with st.expander("更多图表：NDX 价格、Fear & Greed、PE"):
            components.html(
                ui_charts.chart_html(
                    [
                        ui_charts.plain_panel(
                            "NDX 收盘价",
                            price,
                            [{"y": round(float(recent_high), 2), "label": "历史最高收盘价"}]
                            if recent_high is not None
                            else [],
                        ),
                        ui_charts.plain_panel("美股 Fear & Greed", fgi_series, [{"y": 50, "label": "50"}]),
                        ui_charts.plain_panel(
                            "P/E（快照积累）", pe_series, [{"y": 35, "label": "35"}, {"y": 22, "label": "22"}]
                        ),
                    ],
                    620,
                ),
                height=630,
            )
            st.caption("各指标保留原始更新频率；空白区间表示该来源没有历史观测，不做插值。PE 历史来自每日快照，样本较短。")
        chart_frames = (range_label, price, drawdown_series, vxn_series, fgi_series, pe_series)
    else:
        st.html('<p class="ins" style="color:var(--ink-2)">NDX 历史序列不可用，暂无走势图。</p>')

# ---------------------------------------------------------------------------
# Data health: full audit trail, diagnostics, exports and emergency override.
# Collapsed when everything is normal; opened automatically on any issue.
# ---------------------------------------------------------------------------
st.html('<div id="data-health"></div>' + ui.section("数据健康", "Diagnostics"))
health_open = bool(issues) or decision_kind != "final"
health = st.expander(
    "诊断明细、导出与手动覆盖" + ("（有异常，已展开）" if health_open else ""),
    expanded=health_open,
)

with health:
    st.subheader("当前定投建议")
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "最终建议倍数",
        f"{final_multiplier:.2f}×" if final_multiplier is not None else "暂不可用",
    )
    zone_label = zone["label"] if zone else "暂无数据"
    if zone is not None and not drawdown_decidable:
        zone_label += "（参考）"
    c2.metric("回撤状态", zone_label)
    level_text = f"{level} 级" if level is not None else "暂无数据"
    if level is not None and not vxn_live:
        level_text += "（未用于升档）"
    c3.metric("VXN 恐慌级别", level_text)

    if decision_kind == "final":
        st.success(
            f"最终建议倍数 {final_multiplier:.2f}×：NDX 为 ^NDX 正式指数有效数据，"
            f"VXN {vxn_value:.2f} 已通过有效性校验。"
        )
    elif decision_kind == "proxy":
        st.warning(
            f"NDX 当前使用 QQQ 代理数据。代理推算参考倍数为 {proxy_multiplier:.2f}×，"
            "但这不作为官方 Nasdaq-100 指数的最终建议倍数，也不会写入正式历史。"
        )
    elif decision_kind == "base_only":
        st.warning(
            f"VXN 数据无效或不可用，情绪调整不可用。回撤基础倍数为 {base_multiplier:.2f}×，"
            "这不是完整的最终建议倍数；页面不会给出最终建议倍数。"
        )
    elif decision_kind == "reference_only":
        st.warning(
            "NDX 当前为会话缓存/历史回退、数据过期或历史窗口不足，回撤仅作参考，"
            "最终动态倍数不可用。"
        )
    else:
        st.error(
            "NDX 回撤数据无效或不可用，最终动态倍数不可用；"
            "不会按 extreme 档位或 1.0× 处理。"
        )
    st.info(summary)

    def card(col, title, rows, source, date, updated_at=None, saved_at=None):
        with col:
            st.subheader(title)
            for label, value in rows:
                st.metric(label, value)
            caption = (
                f"来源：{source or '未知'}\n"
                f"数据日期：{_format_date(date, '暂无数据')}\n"
                f"本次获取时间：{_format_fetch_time(updated_at)}"
            )
            if saved_at:
                caption += f"\n保存日期：{_format_date(saved_at, '—')}"
            st.caption(caption)

    st.subheader("核心市场指标")
    cols = st.columns(4)
    ndx_value_text = (
        f"{ndx['value']:,.2f}" if ndx.get("value") is not None else "暂无数据"
    )
    if high_info is None:
        high_text = "暂无数据"
    else:
        high_text = f"{high_info['high']:,.2f}"
        if high_info.get("origin") == "saved_snapshot":
            high_text += "（历史保存口径）"
        elif not high_info.get("window_ok"):
            high_text += f"（{high_info.get('window')} 个有效交易日）"
    dd_text = f"{dd * 100:.1f}%" if dd is not None else "暂无数据"
    if dd is not None and not drawdown_decidable:
        dd_text += "（参考）"
    zone_display = zone["label"] if zone else "暂无数据"
    if zone is not None and not drawdown_decidable:
        zone_display += "（参考）"
    ndx_is_proxy = bool(ndx.get("proxy"))
    ndx_card_title = "Nasdaq-100 回撤（QQQ 代理）" if ndx_is_proxy else "Nasdaq-100 回撤"
    if ndx_live:
        ndx_current_label = "当前 Nasdaq-100（QQQ 代理）" if ndx_is_proxy else "当前 Nasdaq-100"
    elif ndx.get("value") is not None:
        ndx_current_label = "最近有效 Nasdaq-100（QQQ 代理）" if ndx_is_proxy else "最近有效 Nasdaq-100"
    else:
        ndx_current_label = "当前 Nasdaq-100（QQQ 代理）" if ndx_is_proxy else "当前 Nasdaq-100"
    vxn_value_label = (
        "实时值" if vxn_live else ("最近有效值" if vxn.get("value") is not None else "实时值")
    )
    if vxn.get("value") is None:
        vxn_usage_text = "不可用"
    elif vxn_live and decision_kind == "proxy":
        vxn_usage_text = "仅参与 QQQ 代理参考计算（不用于正式 NDX 最终倍数）"
    elif ndx_is_proxy:
        vxn_usage_text = "仅展示，未用于正式 NDX 升档"
    elif vxn_live:
        vxn_usage_text = "已参与升档判断"
    else:
        vxn_usage_text = "仅展示，未用于升档"
    card(
        cols[0],
        ndx_card_title,
        [
            (ndx_current_label, ndx_value_text),
            ("历史最高收盘价", high_text),
            ("历史高点日期", _format_date(high_date, "暂无数据")),
            ("距高点回撤", dd_text),
            ("状态", zone_display),
        ],
        ndx.get("source"),
        ndx.get("date"),
        ndx.get("updated_at"),
        ndx.get("saved_at"),
    )
    card(
        cols[1],
        "VXN 恐慌指数",
        [
            (vxn_value_label, f"{vxn['value']:.2f}" if vxn.get("value") is not None else "暂无数据"),
            ("评分", _format_score(scores["vxn"])),
            ("情绪调整用途", vxn_usage_text),
        ],
        vxn.get("source"),
        vxn.get("date"),
        vxn.get("updated_at"),
        vxn.get("saved_at"),
    )
    card(
        cols[2],
        "股票市场 FGI",
        [("最新值", f"{fgi['value']:.0f}" if fgi.get("value") is not None else "暂无数据"), ("仓位作用", "仅展示")],
        fgi.get("source"),
        fgi.get("date"),
        fgi.get("updated_at"),
        fgi.get("saved_at"),
    )
    with cols[2]:
        st.caption("美国股票市场情绪参考，不参与 Nasdaq-100 仓位决策。")
    card(
        cols[3],
        "PE 市盈率",
        [
            ("实时值", f"{pe['value']:.2f}" if pe.get("value") is not None else "暂无数据"),
            ("评分", _format_score(scores["pe"])),
        ],
        pe.get("source"),
        pe.get("date"),
        pe.get("updated_at"),
        pe.get("saved_at"),
    )

    for label, item in (("Nasdaq-100", ndx), ("VXN", vxn), ("FGI", fgi), ("PE", pe)):
        state = item.get("data_state", "unavailable")
        if state == "ok":
            continue
        if state == "proxy":
            st.warning(
                f"{label} 使用 QQQ 代理数据（行情日期 {item.get('date') or '未知'}）。"
                "代理推算结果不是官方 Nasdaq-100 指数信号，仅作参考。"
            )
        elif state == "session_fallback":
            proxy_note = "（缓存值为 QQQ 代理数据）" if item.get("proxy") else ""
            st.warning(
                f"{label} 会话缓存回退{proxy_note}：数据源暂不可用，正在展示会话缓存中的最近一次有效值；"
                "该值仅展示，不驱动最终倍数。"
            )
        elif state == "history_fallback":
            market_date = item.get("date") or "未知"
            saved_date = item.get("saved_at") or "未知"
            if item.get("stale"):
                st.warning(
                    f"{label} 历史数据回退：历史数据已过期"
                    f"（行情日期 {market_date}，保存日期 {saved_date}）；"
                    "该值仅展示，不驱动最终倍数。"
                )
            else:
                st.warning(
                    f"{label} 历史数据回退：数据源暂不可用，正在展示历史保存记录中的最近一次有效值"
                    f"（行情日期 {market_date}，保存日期 {saved_date}）；"
                    "该值仅展示，不驱动最终倍数。"
                )
        elif state == "stale":
            st.warning(
                f"{label} 行情日期已过期（{item.get('date') or '未知'}），仅展示，不驱动最终倍数。"
            )
        elif state == "invalid":
            st.error(f"{label} 数据无效，已拒绝异常数值；该指标显示为暂无数据。")
        else:
            st.error(f"{label} 数据不可用，且没有可用的有效回退数据。")

    if ndx_market_date and vxn_market_date and ndx_market_date != vxn_market_date:
        both_history = (
            ndx.get("data_state") == "history_fallback"
            and vxn.get("data_state") == "history_fallback"
        )
        prefix = "历史回退日期不一致" if both_history else "NDX 与 VXN 数据日期不一致"
        st.warning(
            f"{prefix}：NDX 行情日期 {ndx_market_date}，VXN 行情日期 {vxn_market_date}；"
            "两者不能视为同一时点的数据。相关数据仅供参考，"
            "不得将混合或回退数据用于正式倍数决策。"
        )

    if ndx_series_mismatch:
        st.warning(
            "NDX 当前值与历史序列末值不一致，属于不同数据口径；已拒绝用该序列计算回撤，"
            "最终动态倍数不可用。"
        )
    elif ndx_live and high_info is None:
        st.warning(
            "NDX 缺少可校验的历史序列，无法计算历史最高收盘价；最终动态倍数不可用。"
        )

    st.subheader("当前快照一致性诊断")
    diagnostic_rows = []
    for name, item, drives_decision in (
        ("Nasdaq-100", ndx, True),
        ("VXN", vxn, True),
        ("股票 FGI", fgi, False),
        ("Trailing PE", pe, False),
    ):
        state = item.get("data_state", "unavailable")
        value = item.get("value")
        if value is None:
            value_text = "暂无数据"
        elif name == "股票 FGI":
            value_text = f"{float(value):.1f}"
        else:
            value_text = f"{float(value):.2f}"
        if drives_decision:
            eligible = (
                "可参与建议"
                if ((name == "Nasdaq-100" and ndx_live and drawdown_decidable)
                    or (name == "VXN" and vxn_live and ndx_live and drawdown_decidable))
                else "不可参与建议"
            )
        else:
            eligible = "仅辅助展示"
        diagnostic_rows.append(
            {
                "指标": name,
                "当前值": value_text,
                "数据日期": _format_date(item.get("date"), "—"),
                "本次获取": _format_fetch_time(item.get("updated_at")),
                "状态": STATE_LABELS.get(state, state),
                "决策用途": eligible,
            }
        )
    st.dataframe(pd.DataFrame(diagnostic_rows), hide_index=True, use_container_width=True)
    if final_multiplier is not None:
        st.success("一致性诊断通过：NDX、历史最高收盘价和 VXN 使用可用于同一决策快照的数据。")
    else:
        st.warning("一致性诊断未通过：当前页面仍可查看指标和图表，但不会生成新的最终建议倍数。")

    st.subheader("指标数据状态")
    status_rows = []
    for name, item in (("Nasdaq-100", ndx), ("VXN", vxn), ("FGI", fgi), ("PE", pe)):
        state = item.get("data_state", "unavailable")
        status_label = STATE_LABELS.get(state, state)
        if item.get("proxy") and state != "proxy":
            status_label += "（QQQ 代理）"
        note = item.get("note") or DEFAULT_STATE_NOTES.get(state, "")
        if name == "PE" and item.get("input_mode") != "manual":
            note = "ETF 组合市盈率代理值，不代表官方 Nasdaq-100 指数 PE。"
        status_rows.append(
            {
                "指标": name,
                "状态": status_label,
                "行情日期": _format_date(item.get("date"), "—"),
                "保存日期": _format_date(item.get("saved_at"), "—"),
                "来源": item.get("source"),
                "来源链接": item.get("source_url") or "—",
                "说明": note,
            }
        )
    st.dataframe(pd.DataFrame(status_rows), hide_index=True, use_container_width=True)

    st.subheader("下一档加仓触发条件")
    trigger = get_next_trigger(dd) if drawdown_decidable else None
    if trigger:
        if final_multiplier is not None:
            current_suggestion = f"{final_multiplier:.2f}×"
        elif decision_kind == "proxy":
            current_suggestion = f"{proxy_multiplier:.2f}×（QQQ 代理参考）"
        elif decision_kind == "base_only":
            current_suggestion = (
                f"回撤基础 {base_multiplier:.2f}×（VXN 情绪调整不可用）"
            )
        else:
            current_suggestion = "暂不可用"
        st.write(f"当前回撤：{dd*100:.1f}%　|　当前建议：{current_suggestion}")
        if trigger["next_threshold"] is None:
            st.write("已处于最深回撤档位（≤ -25%）。极端恐慌时最高可提高至 3.0×。")
        else:
            sentiment_condition = trigger["sentiment_condition"]
            if not vxn_live:
                sentiment_condition += "（当前 VXN 数据不可用，情绪条件暂无法确认）"
            st.write(
                f"下一档：回撤达到 {trigger['next_threshold']*100:.0f}%"
                f"（进入 {trigger['next_label']}），距离约 {trigger['distance']*100:.1f} 个百分点。"
                f"情绪确认条件：{sentiment_condition}。"
            )
        if decision_kind == "proxy":
            st.caption("以上为 QQQ 代理数据推算的参考触发条件，不是官方 NDX 信号。")
    else:
        st.warning("回撤数据不足、无效或不可用于决策，无法计算下一档触发条件。")

    if decision_kind == "final" and zone:
        market_status = zone["label"]
    elif decision_kind == "base_only" and zone:
        market_status = f"{zone['label']}（VXN情绪调整不可用）"
    else:
        market_status = "数据不完整"

    row = {
        "date": local_today(),
        "ndx": ndx.get("value"),
        "ndx_date": ndx.get("date"),
        "ath": recent_high,
        "ath_date": high_date,
        "drawdown": dd,
        "drawdown_score": scores["drawdown"],
        "vxn": vxn.get("value") if vxn_live else None,
        "vxn_date": vxn.get("date") if vxn_live else None,
        "vxn_score": scores["vxn"] if vxn_live else None,
        "pe": pe.get("value") if pe_live else None,
        "pe_score": scores["pe"] if pe_live else None,
        "pe_source": pe.get("source") if pe_live else None,
        "total_score": None,
        "confidence": None,
        "multiplier": final_multiplier,
        "market_status": market_status,
        "model_version": MODEL_VERSION,
    }
    snapshot_basis = "|".join(
        str(row.get(key))
        for key in ("ndx_date", "ndx", "ath", "ath_date", "vxn_date", "vxn", "pe", "multiplier")
    )
    snapshot_id = hashlib.sha256(snapshot_basis.encode("utf-8")).hexdigest()[:12]
    row["snapshot_id"] = snapshot_id

    st.subheader("快照与导出")
    st.caption(f"统一快照 ID：`{snapshot_id}`")
    snapshot_export = pd.DataFrame(
        [
            {
                **row,
                "snapshot_created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "ndx_source": ndx.get("source"),
                "vxn_source": vxn.get("source"),
                "fgi_source": fgi.get("source"),
                "pe_source": pe.get("source"),
                "decision_kind": decision_kind,
            }
        ]
    ).to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "下载当前统一快照 CSV",
        data=snapshot_export,
        file_name=f"nasdaq_dashboard_snapshot_{local_today()}.csv",
        mime="text/csv",
        help="导出当前页面使用的统一数据快照、来源和决策状态。",
    )
    if chart_frames is not None:
        range_label, price, drawdown_series, vxn_series, fgi_series, pe_series = chart_frames
        chart_export = pd.DataFrame(index=price.index)
        chart_export.index.name = "date"
        chart_export["ndx_close"] = price
        chart_export["drawdown_pct"] = drawdown_series * 100
        for column_name, series in (
            ("vxn", vxn_series),
            ("stock_fgi", fgi_series),
            ("trailing_pe", pe_series),
        ):
            if not series.empty:
                chart_export = chart_export.join(series.rename(column_name), how="outer")
        st.download_button(
            "下载当前图表数据 CSV",
            data=chart_export.sort_index().to_csv().encode("utf-8-sig"),
            file_name=f"nasdaq_dashboard_chart_{range_label}.csv",
            mime="text/csv",
            help="导出当前时间范围内各指标的原始观测；空缺值保持为空。",
        )
    if drawdown_decidable and ndx_state == "ok" and not manual:
        clean_row = sanitize_for_save(row)
        try:
            backend, save_error = save_history(clean_row)
            partial_note = (
                ""
                if final_multiplier is not None
                else "；VXN/最终倍数不可用，已按空值保存"
            )
            st.caption(
                f"历史快照已保存：{backend}{partial_note}"
                + (f"（{save_error}）" if save_error else "")
            )
        except Exception as exc:
            st.caption(f"历史快照保存失败：{exc}")
    else:
        st.caption(
            "本次未写入历史：仅当 NDX 为正式 ^NDX 有效数据且历史最高收盘价可校验时才保存；"
            "代理、回退、过期、无效数据不会写入正式历史。"
        )

    st.subheader("数据来源与存储")
    st.caption(f"当前存储：{history_backend}" + (f"（{history_error}）" if history_error else ""))
    st.dataframe(
        pd.DataFrame(
            [
                {"项目": "NDX", "值": str(ndx.get("source"))},
                {"项目": "VXN", "值": str(vxn.get("source"))},
                {"项目": "FGI", "值": str(fgi.get("source"))},
                {"项目": "PE", "值": str(pe.get("source"))},
                {"项目": "NDX 主源失败原因", "值": str(ndx.get("primary_error") or "—")},
                {"项目": "NDX 数据状态", "值": STATE_LABELS.get(ndx_state, ndx_state)},
                {"项目": "VXN 数据状态", "值": STATE_LABELS.get(vxn_state, vxn_state)},
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    if st.button("迁移本地 CSV 到 Supabase"):
        result = migrate_local_csv()
        rows_read = result.get("rows_read", 0)
        uploaded = result.get("rows_uploaded", 0)
        failed = result.get("rows_failed", 0)
        if failed:
            migration_summary = f"读取 {rows_read} 行，成功 {uploaded} 行，失败 {failed} 行。"
            if uploaded:
                st.warning(migration_summary)
            else:
                st.error(migration_summary)
            failure_details = result.get("failed_rows") or []
            if failure_details:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "CSV行号": detail.get("row"),
                                "日期": detail.get("date") or "缺失",
                                "错误": detail.get("error") or "未知错误",
                            }
                            for detail in failure_details
                        ]
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
            if result.get("error"):
                st.caption(f"迁移错误：{result['error']}")
        elif result.get("error"):
            st.warning(
                f"读取 {rows_read} 行，上传 {uploaded} 行；{result['error']}"
            )
        else:
            st.success(f"读取 {rows_read} 行，上传 {uploaded} 行。")

    st.subheader("手动覆盖（应急）")
    st.caption("仅在数据源失败时使用。启用后首屏会标记为“使用手动数据”，不会写入历史。")
    st.checkbox("启用手动覆盖", key="manual_override")
    if manual:
        st.number_input("手动 Nasdaq-100", value=manual_defaults["manual_ndx"], key="manual_ndx")
        st.number_input("手动 VXN", value=manual_defaults["manual_vxn"], key="manual_vxn")
        st.number_input(
            "手动股票 FGI（仅展示）", 0.0, 100.0, value=manual_defaults["manual_fgi"], key="manual_fgi"
        )
        st.number_input("手动 PE", 1.0, 100.0, value=manual_defaults["manual_pe"], key="manual_pe")

st.caption(
    "本仪表盘仅用于长期定投节奏辅助，不构成任何投资建议。"
    "市场可能长期高估或低估，情绪指标亦存在失效风险。"
    "定投倍数调整应结合个人现金流、风险承受能力与投资期限。"
)
