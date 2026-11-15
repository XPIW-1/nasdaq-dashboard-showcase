import datetime as dt
import math
from pathlib import Path

import pandas as pd
import pytest
from streamlit import cache_data
from streamlit.testing.v1 import AppTest

from data_sources import ndx as ndx_source
from data_sources import vxn as vxn_source
from model.signals import (
    apply_sentiment_adjustment,
    calculate_base_multiplier,
    calculate_drawdown,
    generate_market_summary,
    get_drawdown_zone,
    get_next_trigger,
    sentiment_level,
)
from utils import helpers

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
TODAY = dt.date.today().isoformat()


def _series(values=None, periods=260):
    index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=periods)
    if values is None:
        values = [100.0 + i * 0.1 for i in range(periods)]
    return pd.Series(values, index=index, dtype=float)


def _flat_history(high=120.0, current=100.0, periods=260):
    values = [high] * periods
    values[-1] = current
    return _series(values, periods=periods)


def _ndx_result(series, value=None, *, proxy=False, source="test NDX", status="ok", error=None):
    if series is not None and len(series):
        ordered = series.sort_index()
        last_value = float(ordered.iloc[-1])
        last_date = ordered.index[-1].date().isoformat()
    else:
        last_value = None
        last_date = None
    return {
        "value": last_value if value is None else value,
        "date": last_date,
        "updated_at": "2026-01-01T00:00:00Z",
        "history": series,
        "symbol": "QQQ" if proxy else "^NDX",
        "source": source,
        "error": error,
        "proxy": proxy,
        "status": "proxy" if proxy else status,
    }


def _vxn_result(value=22.0, series=None, *, status="ok", error=None):
    if series is None and value is not None and math.isfinite(float(value)):
        series = _series([float(value)] * 260)
    return {
        "value": value,
        "date": series.index[-1].date().isoformat() if series is not None and len(series) else None,
        "updated_at": "2026-01-01T00:00:00Z",
        "history": series,
        "source": "test VXN",
        "error": error,
        "proxy": False,
        "status": status,
    }


def _pe_result(value=30.0):
    return {
        "value": value,
        "date": TODAY,
        "updated_at": "2026-01-01T00:00:00Z",
        "history": None,
        "source": "test PE",
        "error": None,
        "status": "ok",
    }


def _run_app(monkeypatch, ndx_result, vxn_result, history=None, pe_result=None, stale=False):
    import data_sources.fear_greed as fgi_mod
    import data_sources.ndx as ndx_mod
    import data_sources.valuation as pe_mod
    import data_sources.vxn as vxn_mod
    import utils.storage as storage_mod

    monkeypatch.setattr(helpers, "is_market_data_stale", lambda *args, **kwargs: stale)
    monkeypatch.setattr(ndx_mod, "fetch_ndx", lambda period="2y": ndx_result)
    monkeypatch.setattr(vxn_mod, "fetch_vxn", lambda period="10y": vxn_result)
    monkeypatch.setattr(
        fgi_mod,
        "fetch_fear_greed",
        lambda: {
            "value": 50.0,
            "date": TODAY,
            "updated_at": "2026-01-01T00:00:00Z",
            "history": None,
            "source": "test FGI",
            "error": None,
        },
    )
    monkeypatch.setattr(pe_mod, "fetch_pe", lambda: pe_result or _pe_result())
    monkeypatch.setattr(
        storage_mod,
        "load_history_preferred",
        lambda: (history if history is not None else pd.DataFrame(), "test", None),
    )
    saved = []

    def fake_save(row):
        saved.append(row)
        return "test", None

    monkeypatch.setattr(storage_mod, "save_history", fake_save)
    monkeypatch.setattr(
        storage_mod, "migrate_local_csv", lambda: {"rows_read": 0, "rows_uploaded": 0}
    )
    cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    return app, saved


def _metric(app, label):
    matches = [item.value for item in app.metric if item.label == label]
    assert matches, f"metric not found: {label}"
    return matches[0]


def _texts(elements):
    return [element.value for element in elements]


INVALID_NDX = [None, float("nan"), float("inf"), float("-inf"), 0.0, -1.0]
INVALID_VXN = [None, float("nan"), float("inf"), float("-inf"), 0.0, -1.0]


@pytest.mark.parametrize("value", INVALID_NDX)
def test_invalid_ndx_never_creates_extreme_or_upgrade(value):
    assert calculate_drawdown(value, 30000.0) is None
    assert get_drawdown_zone(calculate_drawdown(value, 30000.0)) is None
    assert apply_sentiment_adjustment(calculate_drawdown(value, 30000.0), 100.0) is None
    assert calculate_base_multiplier(calculate_drawdown(value, 30000.0)) is None


@pytest.mark.parametrize("value", INVALID_NDX)
def test_invalid_high_never_creates_drawdown(value):
    assert calculate_drawdown(27000.0, value) is None


@pytest.mark.parametrize("value", INVALID_VXN)
def test_invalid_vxn_never_upgrades(value):
    # None means "not supplied" and may still return the base tier, but a
    # supplied unusable value must return no multiplier at all.
    if value is None:
        assert apply_sentiment_adjustment(-0.26, value) == 2.5
    else:
        assert apply_sentiment_adjustment(-0.26, value) is None
    assert sentiment_level(value) is None


def test_finite_high_vxn_still_follows_existing_thresholds():
    # A high but finite VXN is a real observation and must not be capped.
    assert sentiment_level(100.0) == 4
    assert apply_sentiment_adjustment(-0.09, 100.0) == 1.5
    assert apply_sentiment_adjustment(-0.14, 100.0) == 2.0
    assert apply_sentiment_adjustment(-0.20, 100.0) == 2.5
    assert apply_sentiment_adjustment(-0.26, 100.0) == 3.0
    assert apply_sentiment_adjustment(-0.26, 45.0) == 2.5
    assert apply_sentiment_adjustment(-0.26, 45.01) == 3.0


@pytest.mark.parametrize(
    "drawdown",
    [None, float("nan"), float("inf"), float("-inf"), 0.1, 1.0, -1.1, -2.0],
)
def test_invalid_drawdown_is_not_extreme(drawdown):
    assert get_drawdown_zone(drawdown) is None
    assert apply_sentiment_adjustment(drawdown, 100.0) is None
    assert get_next_trigger(drawdown) is None


def test_invalid_data_summary_has_no_nan_or_false_extreme():
    summary = generate_market_summary(float("nan"), 50.0, 1.0)
    assert "nan" not in summary.lower()
    assert "极端" not in summary
    assert "不可用" in summary

    summary = generate_market_summary(float("inf"), 50.0, 3.0)
    assert "nan" not in summary.lower()
    assert "极端" not in summary

    summary = generate_market_summary(
        -0.30, None, None, vxn_valid=False, base_multiplier=2.5
    )
    assert "情绪调整不可用" in summary
    assert "最终建议倍数暂不可用" in summary
    assert "2.50×" in summary


def test_normal_zone_boundaries_are_unchanged():
    assert get_drawdown_zone(0.0)["key"] == "normal"
    assert get_drawdown_zone(-0.0799)["key"] == "normal"
    assert get_drawdown_zone(-0.08)["key"] == "mild"
    assert get_drawdown_zone(-0.12)["key"] == "moderate"
    assert get_drawdown_zone(-0.18)["key"] == "deep"
    assert get_drawdown_zone(-0.25)["key"] == "extreme"
    assert calculate_base_multiplier(-0.25) == 2.5


def test_price_history_requires_datetime_index():
    with pytest.raises(ndx_source.InvalidPriceData):
        ndx_source.clean_price_series(pd.Series([1.0, 2.0]))
    with pytest.raises(vxn_source.InvalidVxnData):
        vxn_source.clean_price_series(pd.Series([1.0, 2.0]))


def test_current_above_high_is_a_series_mismatch():
    assert calculate_drawdown(30000.0, 25000.0) is None
    assert get_drawdown_zone(calculate_drawdown(30000.0, 25000.0)) is None


def test_ndx_source_sorts_dedupes_and_filters_non_finite(monkeypatch):
    index = pd.to_datetime(
        [
            "2026-09-03",
            "2026-09-01",
            "2026-09-02",
            "2026-09-02",
            "2026-09-04",
            "2026-09-08",
        ]
    )
    frame = pd.DataFrame(
        {
            "Close": [110.0, 100.0, float("nan"), 105.0, float("inf"), 121.0],
        },
        index=index,
    )

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            if self.symbol == "^NDX":
                return frame
            raise RuntimeError("QQQ should not be needed")

    monkeypatch.setattr(ndx_source.yf, "Ticker", FakeTicker)
    result = ndx_source.fetch_ndx("1y")
    assert result["proxy"] is False
    assert result["status"] == "ok"
    assert result["value"] == 121.0
    history = result["history"]
    assert list(history.index) == sorted(history.index)
    assert not history.index.duplicated().any()
    assert (history > 0).all()
    assert history.loc[pd.Timestamp("2026-09-02")] == 105.0


def test_ndx_source_rejects_invalid_latest_and_keeps_primary_reason(monkeypatch):
    bad = pd.DataFrame(
        {"Close": [100.0, 0.0]},
        index=pd.to_datetime(["2026-09-14", "2026-09-15"]),
    )
    good = pd.DataFrame(
        {"Close": [400.0, 405.0]},
        index=pd.to_datetime(["2026-09-14", "2026-09-15"]),
    )

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            if self.symbol == "^NDX":
                return bad
            return good

    monkeypatch.setattr(ndx_source.yf, "Ticker", FakeTicker)
    result = ndx_source.fetch_ndx("1y")
    assert result["proxy"] is True and result["symbol"] == "QQQ"
    assert result["value"] == 405.0
    assert "latest observation" in result["primary_error"]
    assert result["status"] == "proxy"


def test_vxn_source_keeps_finite_high_value_and_rejects_invalid_latest(monkeypatch):
    index = pd.to_datetime(
        [
            "2026-09-01",
            "2026-09-03",
            "2026-09-02",
            "2026-09-02",
            "2026-09-04",
            "2026-09-08",
        ]
    )
    frame = pd.DataFrame(
        {
            "Close": [20.0, 100.0, float("nan"), 25.0, 0.0, 100.0],
        },
        index=index,
    )

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            return frame

    monkeypatch.setattr(vxn_source.yf, "Ticker", FakeTicker)
    result = vxn_source.fetch_vxn("10y")
    assert result["status"] == "ok" and result["value"] == 100.0
    assert sentiment_level(result["value"]) == 4

    bad_latest = pd.DataFrame(
        {"Close": [20.0, 0.0]},
        index=pd.to_datetime(["2026-09-14", "2026-09-15"]),
    )

    class BadTicker:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            return bad_latest

    monkeypatch.setattr(vxn_source.yf, "Ticker", BadTicker)
    result = vxn_source.fetch_vxn("10y")
    assert result["value"] is None
    assert result["status"] == "invalid"
    assert sentiment_level(result["value"]) is None


def test_rolling_high_uses_last_252_valid_days_and_actual_high_date():
    index = pd.bdate_range("2025-01-01", periods=320)
    values = [500.0] * 60 + [120.0] * 259 + [100.0]
    series = pd.Series(values, index=index, dtype=float)
    clean = ndx_source.clean_price_series(series)
    result = ndx_source.rolling_high(clean, 252)
    assert result["window"] == 252
    assert result["window_ok"] is True
    assert result["high"] == 120.0
    assert result["high_date"] == index[68].date().isoformat()


def test_ndx_invalid_keeps_final_multiplier_unavailable(monkeypatch):
    series = _flat_history()
    ndx = _ndx_result(series, value=float("nan"), status="invalid", error="bad")
    vxn = _vxn_result(100.0)
    app, saved = _run_app(monkeypatch, ndx, vxn)
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert _metric(app, "回撤状态") == "暂无数据"
    assert not any("极端回撤" in text for text in _texts(app.info))
    assert not saved


def test_vxn_invalid_shows_base_but_no_final_multiplier(monkeypatch):
    series = _flat_history(high=120.0, current=100.0)
    ndx = _ndx_result(series)
    vxn = _vxn_result(float("nan"), series=None, status="invalid", error="bad")
    app, saved = _run_app(monkeypatch, ndx, vxn)
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert _metric(app, "VXN 恐慌级别") == "暂无数据"
    warnings = _texts(app.warning)
    assert any("情绪调整不可用" in text and "1.50×" in text for text in warnings)
    assert any("回撤基础倍数为 1.50×" in text for text in _texts(app.info))
    # The official NDX snapshot is still recorded, but VXN and the final
    # multiplier must be persisted as unavailable rather than as a fake base.
    assert len(saved) == 1
    assert saved[0]["vxn"] is None
    assert saved[0]["vxn_score"] is None
    assert saved[0]["multiplier"] is None


def test_session_cache_is_not_overwritten_by_invalid_value(monkeypatch):
    valid_series = _flat_history(high=120.0, current=100.0)
    valid_ndx = _ndx_result(valid_series)
    invalid_ndx = _ndx_result(None, value=float("nan"), status="invalid", error="bad")
    state = {"ndx": valid_ndx}
    import data_sources.ndx as ndx_mod
    import data_sources.vxn as vxn_mod
    import data_sources.fear_greed as fgi_mod
    import data_sources.valuation as pe_mod
    import utils.storage as storage_mod

    monkeypatch.setattr(helpers, "is_market_data_stale", lambda *args, **kwargs: False)
    monkeypatch.setattr(ndx_mod, "fetch_ndx", lambda period="2y": state["ndx"])
    monkeypatch.setattr(vxn_mod, "fetch_vxn", lambda period="10y": _vxn_result(22.0))
    monkeypatch.setattr(
        fgi_mod,
        "fetch_fear_greed",
        lambda: {
            "value": 50.0,
            "date": TODAY,
            "history": None,
            "source": "test FGI",
            "error": None,
        },
    )
    monkeypatch.setattr(pe_mod, "fetch_pe", lambda: _pe_result())
    monkeypatch.setattr(
        storage_mod, "load_history_preferred", lambda: (pd.DataFrame(), "test", None)
    )
    monkeypatch.setattr(storage_mod, "save_history", lambda row: ("test", None))
    monkeypatch.setattr(
        storage_mod, "migrate_local_csv", lambda: {"rows_read": 0, "rows_uploaded": 0}
    )

    cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert _metric(app, "最终建议倍数") == "1.50×"
    cached_before = app.session_state["last_valid_ndx"]["value"]
    assert cached_before == 100.0

    state["ndx"] = invalid_ndx
    cache_data.clear()
    app.run()
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert app.session_state["last_valid_ndx"]["value"] == 100.0
    assert any("会话缓存" in text for text in _texts(app.warning))


def test_qqq_proxy_is_explicit_and_not_final(monkeypatch):
    series = _flat_history(high=120.0, current=96.0)
    ndx = _ndx_result(
        series,
        proxy=True,
        source="Yahoo Finance QQQ（Nasdaq-100 代理）",
    )
    vxn = _vxn_result(22.0)
    app, saved = _run_app(monkeypatch, ndx, vxn)
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert any("QQQ 代理数据" in text for text in _texts(app.warning))
    assert any("代理参考" in text for text in _texts(app.info))
    status = app.dataframe[0].value
    assert status.loc[status["指标"] == "Nasdaq-100", "状态"].iloc[0] == "QQQ 代理数据"
    assert not saved


def test_history_fallback_is_same_row_and_never_drives_multiplier(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-09-01",
                "ndx": 100.0,
                "ndx_date": "2026-08-28",
                "ath": 120.0,
                "ath_date": "2026-06-01",
                "vxn": 22.0,
                "vxn_date": "2026-08-28",
            }
        ]
    )
    ndx = _ndx_result(None, value=None, status="unavailable", error="offline")
    vxn = _vxn_result(None, series=None, status="unavailable", error="offline")
    app, saved = _run_app(monkeypatch, ndx, vxn, history=history)
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert _metric(app, "回撤状态") == "中度回调（参考）"
    assert any("历史数据回退" in text for text in _texts(app.warning))
    assert not saved


def test_live_current_and_history_mismatch_blocks_multiplier(monkeypatch):
    series = _flat_history(high=120.0, current=100.0)
    ndx = _ndx_result(series, value=110.0)
    app, saved = _run_app(monkeypatch, ndx, _vxn_result(22.0))
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert any("历史序列末值不一致" in text for text in _texts(app.warning))
    assert not saved


def test_mixed_current_and_high_rows_never_create_drawdown(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-09-01",
                "ndx": 300.0,
                "ndx_date": "2026-08-31",
                "ath": 250.0,
                "ath_date": "2026-06-01",
                "vxn": 22.0,
                "vxn_date": "2026-08-31",
            }
        ]
    )
    ndx = _ndx_result(None, value=None, status="unavailable", error="offline")
    vxn = _vxn_result(None, series=None, status="unavailable", error="offline")
    app, saved = _run_app(monkeypatch, ndx, vxn, history=history)
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert _metric(app, "回撤状态") == "暂无数据"
    assert not saved


def test_short_history_can_drive_decision_when_all_time_high_is_available(monkeypatch):
    series = _flat_history(high=120.0, current=100.0, periods=100)
    ndx = _ndx_result(series)
    vxn = _vxn_result(22.0)
    app, saved = _run_app(monkeypatch, ndx, vxn)
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "1.50×"
    assert _metric(app, "历史最高收盘价") == "120.00"
    assert _metric(app, "回撤状态") == "中度回调"
    assert saved


def test_stale_live_ndx_is_display_only(monkeypatch):
    series = _flat_history(high=120.0, current=100.0)
    ndx = _ndx_result(series)
    vxn = _vxn_result(22.0)
    app, saved = _run_app(monkeypatch, ndx, vxn, stale=True)
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert _metric(app, "回撤状态") == "中度回调（参考）"
    assert any("已过期" in text for text in _texts(app.warning))
    assert not saved


def test_app_cleans_unordered_duplicate_nonfinite_history(monkeypatch):
    index = pd.bdate_range("2025-01-01", periods=320)
    values = [500.0] * 60 + [120.0] * 259 + [100.0]
    series = pd.Series(values, index=index, dtype=float)
    # Invalid values are removed before computing the all-time high.
    series.iloc[5] = float("nan")
    series.iloc[15] = float("inf")
    series.iloc[25] = 0.0
    series.iloc[35] = -5.0
    duplicate_date = series.index[200]
    duplicate = pd.Series([120.0], index=pd.DatetimeIndex([duplicate_date]))
    messy = pd.concat([series, duplicate]).sample(frac=1.0, random_state=7)

    app, _saved = _run_app(
        monkeypatch,
        _ndx_result(messy, value=100.0),
        _vxn_result(22.0),
    )
    assert not app.exception
    # The high uses the full cleaned history (README: all available history).
    assert _metric(app, "历史最高收盘价") == "500.00"
    assert _metric(app, "回撤状态") == "极端回撤"


def test_saved_row_contains_no_non_finite_values(monkeypatch):
    series = _flat_history(high=120.0, current=100.0)
    ndx = _ndx_result(series)
    vxn = _vxn_result(22.0)
    pe = _pe_result(float("inf"))
    app, saved = _run_app(monkeypatch, ndx, vxn, pe_result=pe)
    assert not app.exception
    assert len(saved) == 1
    row = saved[0]
    for field in (
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
    ):
        value = row[field]
        assert value is None or (isinstance(value, (int, float)) and math.isfinite(value))
    assert row["pe"] is None
    assert row["multiplier"] == 1.5
