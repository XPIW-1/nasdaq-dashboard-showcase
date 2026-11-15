from pathlib import Path

import pandas as pd
from streamlit import cache_data
from streamlit.testing.v1 import AppTest

import data_sources.fear_greed as fgi_mod
import data_sources.ndx as ndx_mod
import data_sources.valuation as pe_mod
import data_sources.vxn as vxn_mod
import utils.storage as storage_mod
from utils import helpers

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
DATE = "2026-10-28"
FETCHED_AT = "2026-10-29T08:00:00Z"
TODAY = pd.Timestamp.today().date().isoformat()
COMPOSITE_WARNING = (
    "当前 NDX 回撤不可用，综合评分不包含有效的 NDX 回撤信号，"
    "仅供参考，不构成定投决策依据。"
)


def _frame(values, end=DATE):
    index = pd.bdate_range(end=pd.Timestamp(end), periods=len(values))
    return pd.DataFrame({"Close": values}, index=index)


def _install_ticker(monkeypatch, behaviors):
    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            behavior = behaviors[self.symbol]
            if isinstance(behavior, Exception):
                raise behavior
            return behavior.copy()

    monkeypatch.setattr(ndx_mod.yf, "Ticker", FakeTicker)


def test_invalid_ndx_latest_error_has_single_prefix(monkeypatch):
    values = [120.0] * 300
    values[-1] = float("nan")
    _install_ticker(
        monkeypatch,
        {"^NDX": _frame(values), "QQQ": RuntimeError("qqq down")},
    )

    result = ndx_mod.fetch_ndx("2y")

    assert result["status"] == "invalid"
    assert result["value"] is None
    assert result["proxy"] is False
    assert result["is_official"] is False
    assert result["error"].count("^NDX:") == 1
    assert result["error"].count("QQQ:") == 1
    assert "latest observation" in result["error"]
    assert "qqq down" in result["error"]


def test_primary_failure_keeps_reason_in_proxy_result(monkeypatch):
    values = [760.0] * 299 + [725.0]
    _install_ticker(
        monkeypatch,
        {"^NDX": RuntimeError("primary offline"), "QQQ": _frame(values)},
    )

    result = ndx_mod.fetch_ndx("2y")

    assert result["status"] == "proxy"
    assert result["proxy"] is True
    assert result["is_official"] is False
    assert result["symbol"] == "QQQ"
    assert result["value"] == 725.0
    assert result["date"] == DATE
    assert len(result["history"]) == 300
    assert result["error"] is None
    assert result["primary_error"] == "^NDX: primary offline"
    assert result["primary_error"].count("^NDX:") == 1
    assert "primary offline" in result["primary_error"]


def test_both_source_failures_are_distinguishable(monkeypatch):
    _install_ticker(
        monkeypatch,
        {"^NDX": RuntimeError("ndx down"), "QQQ": RuntimeError("qqq down")},
    )

    result = ndx_mod.fetch_ndx("2y")

    assert result["status"] == "unavailable"
    assert result["value"] is None
    assert result["history"] is None
    assert result["proxy"] is False
    assert result["is_official"] is False
    assert result["error"].count("^NDX:") == 1
    assert result["error"].count("QQQ:") == 1
    assert "ndx down" in result["error"]
    assert "qqq down" in result["error"]


def test_invalid_primary_with_valid_qqq_is_proxy_without_double_prefix(monkeypatch):
    bad = [120.0] * 300
    bad[-1] = float("nan")
    qqq = [760.0] * 299 + [725.0]
    _install_ticker(
        monkeypatch,
        {"^NDX": _frame(bad), "QQQ": _frame(qqq)},
    )

    result = ndx_mod.fetch_ndx("2y")

    assert result["status"] == "proxy"
    assert result["proxy"] is True
    assert result["is_official"] is False
    assert result["symbol"] == "QQQ"
    assert result["value"] == 725.0
    assert result["primary_error"].count("^NDX:") == 1
    assert "latest observation" in result["primary_error"]


def test_primary_success_fields_are_unchanged(monkeypatch):
    ndx = [120.0] * 299 + [100.0]
    qqq = [760.0] * 299 + [725.0]
    _install_ticker(
        monkeypatch,
        {"^NDX": _frame(ndx), "QQQ": _frame(qqq)},
    )

    result = ndx_mod.fetch_ndx("2y")

    assert result["status"] == "ok"
    assert result["proxy"] is False
    assert result["is_official"] is True
    assert result["symbol"] == "^NDX"
    assert result["value"] == 100.0
    assert result["date"] == DATE
    assert result["error"] is None
    assert result["primary_error"] is None
    assert result["fallback_reason"] is None
    assert len(result["history"]) == 300


def _series(high=120.0, current=100.0, periods=300):
    index = pd.bdate_range(end=pd.Timestamp(DATE), periods=periods)
    values = [float(high)] * periods
    values[-1] = float(current)
    return pd.Series(values, index=index, dtype=float)


def _official_ndx(series=None):
    series = _series() if series is None else series
    return {
        "value": float(series.iloc[-1]),
        "date": DATE,
        "updated_at": FETCHED_AT,
        "history": series,
        "symbol": "^NDX",
        "source": "Yahoo Finance (^NDX)",
        "error": None,
        "proxy": False,
        "is_official": True,
        "status": "ok",
    }


def _unavailable_ndx():
    return {
        "value": None,
        "date": None,
        "updated_at": None,
        "history": None,
        "symbol": "^NDX",
        "source": "Yahoo Finance (^NDX); QQQ fallback",
        "error": "ndx down; qqq down",
        "proxy": False,
        "is_official": False,
        "status": "unavailable",
    }


def _vxn(value=22.0, history=True):
    series = _series(high=value, current=value, periods=260) if history else None
    return {
        "value": value,
        "date": DATE if series is not None else None,
        "updated_at": FETCHED_AT if series is not None else None,
        "history": series,
        "source": "Yahoo Finance (^VXN)",
        "error": None,
        "proxy": False,
        "is_official": series is not None,
        "status": "ok" if series is not None else "unavailable",
    }


def _run_app(monkeypatch, ndx_result, vxn_result):
    monkeypatch.setattr(helpers, "is_market_data_stale", lambda *args, **kwargs: False)
    monkeypatch.setattr(ndx_mod, "fetch_ndx", lambda period="2y": ndx_result)
    monkeypatch.setattr(vxn_mod, "fetch_vxn", lambda period="10y": vxn_result)
    monkeypatch.setattr(
        fgi_mod,
        "fetch_fear_greed",
        lambda: {
            "value": 50.0,
            "date": TODAY,
            "updated_at": FETCHED_AT,
            "history": None,
            "source": "test FGI",
            "error": None,
        },
    )
    monkeypatch.setattr(
        pe_mod,
        "fetch_pe",
        lambda: {
            "value": 30.0,
            "date": TODAY,
            "updated_at": FETCHED_AT,
            "history": None,
            "source": "test PE",
            "error": None,
            "status": "ok",
            "usable_for_model": True,
        },
    )
    monkeypatch.setattr(
        storage_mod, "load_history_preferred", lambda: (pd.DataFrame(), "test", None)
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
    for item in app.metric:
        if item.label == label:
            return item.value
    raise AssertionError(f"metric not found: {label}")


def _texts(elements):
    return [element.value for element in elements]


def test_ndx_and_vxn_cards_label_fetch_time_not_source_update(monkeypatch):
    app, _saved = _run_app(monkeypatch, _official_ndx(), _vxn())
    assert not app.exception

    captions = _texts(app.caption)
    ndx_captions = [text for text in captions if "Yahoo Finance (^NDX)" in text]
    vxn_captions = [text for text in captions if "Yahoo Finance (^VXN)" in text]

    assert ndx_captions and vxn_captions
    for text in ndx_captions + vxn_captions:
        assert "本次获取时间：2026-10-29 16:00:00（台北时间）" in text
    assert not any("最后更新时间" in text for text in captions)


def test_normal_scenario_has_no_unavailable_warning(monkeypatch):
    app, saved = _run_app(monkeypatch, _official_ndx(), _vxn())
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "1.50×"
    warnings = _texts(app.warning)
    assert COMPOSITE_WARNING not in warnings
    assert not any("NDX 回撤不可用" in text for text in warnings)
    assert len(saved) == 1


def test_ndx_unavailable_shows_no_composite_and_no_multiplier(monkeypatch):
    app, saved = _run_app(monkeypatch, _unavailable_ndx(), _vxn())
    assert not app.exception
    assert not any(item.label == "综合评分" for item in app.metric)
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert COMPOSITE_WARNING not in _texts(app.warning)
    assert not saved


