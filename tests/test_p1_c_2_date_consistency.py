from pathlib import Path

import pandas as pd
from streamlit import cache_data
from streamlit.testing.v1 import AppTest

import data_sources.fear_greed as fgi_mod
import data_sources.ndx as ndx_mod
import data_sources.valuation as pe_mod
import data_sources.vxn as vxn_mod
import utils.storage as storage
from utils import helpers

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
DATE = "2026-10-28"
TODAY = pd.Timestamp.today().date().isoformat()


def _series(high=120.0, current=100.0, periods=300, end=DATE):
    index = pd.bdate_range(end=pd.Timestamp(end), periods=periods)
    values = [float(high)] * periods
    values[-1] = float(current)
    return pd.Series(values, index=index, dtype=float)


def _ndx_payload(date=DATE, proxy=False, current=100.0):
    series = _series(current=current)
    return {
        "value": float(current),
        "date": date,
        "updated_at": "2026-10-29T08:00:00Z",
        "history": series,
        "symbol": "QQQ" if proxy else "^NDX",
        "source": (
            "Yahoo Finance QQQ（Nasdaq-100 代理）"
            if proxy
            else "Yahoo Finance (^NDX)"
        ),
        "error": None,
        "proxy": proxy,
        "is_official": not proxy,
        "status": "proxy" if proxy else "ok",
    }


def _vxn_payload(date=DATE, value=22.0):
    series = _series(high=value, current=value, periods=260, end=date) if date else None
    return {
        "value": float(value),
        "date": date,
        "updated_at": "2026-10-29T08:00:00Z",
        "history": series,
        "source": "Yahoo Finance (^VXN)",
        "error": None,
        "proxy": False,
        "is_official": series is not None,
        "status": "ok" if series is not None else "unavailable",
    }


def _unavailable_ndx():
    return {
        "value": None,
        "date": None,
        "history": None,
        "symbol": "^NDX",
        "source": "Yahoo Finance (^NDX)",
        "error": "offline",
        "proxy": False,
        "is_official": False,
        "status": "unavailable",
    }


def _unavailable_vxn():
    return {
        "value": None,
        "date": None,
        "history": None,
        "source": "Yahoo Finance (^VXN)",
        "error": "offline",
        "proxy": False,
        "is_official": False,
        "status": "unavailable",
    }


def _run(monkeypatch, ndx_result, vxn_result, history=None):
    monkeypatch.setattr(helpers, "is_market_data_stale", lambda *a, **k: False)
    monkeypatch.setattr(ndx_mod, "fetch_ndx", lambda period="2y": ndx_result)
    monkeypatch.setattr(vxn_mod, "fetch_vxn", lambda period="10y": vxn_result)
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
    monkeypatch.setattr(
        pe_mod,
        "fetch_pe",
        lambda: {
            "value": 30.0,
            "date": TODAY,
            "history": None,
            "source": "test PE",
            "error": None,
            "status": "ok",
            "usable_for_model": True,
        },
    )
    monkeypatch.setattr(
        storage,
        "load_history_preferred",
        lambda: (history if history is not None else pd.DataFrame(), "test", None),
    )
    saved = []

    def fake_save(row):
        saved.append(row)
        return "test", None

    monkeypatch.setattr(storage, "save_history", fake_save)
    monkeypatch.setattr(
        storage, "migrate_local_csv", lambda: {"rows_read": 0, "rows_uploaded": 0}
    )
    cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    return app, saved


def _metric(app, label):
    for item in app.metric:
        if item.label == label:
            return item.value
    return None


def _warnings(app):
    return [item.value for item in app.warning]


def _has_mismatch_warning(app, ndx_date, vxn_date):
    return any(
        "NDX 行情日期" in text
        and "VXN 行情日期" in text
        and ndx_date in text
        and vxn_date in text
        and "不能视为同一时点" in text
        for text in _warnings(app)
    )


def test_live_ndx_vs_history_vxn_date_mismatch(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-10-28",
                "vxn": 22.0,
                "vxn_date": "2026-10-27",
            }
        ]
    )
    app, saved = _run(monkeypatch, _ndx_payload(DATE), _unavailable_vxn(), history)
    assert not app.exception
    assert _has_mismatch_warning(app, "2026-10-28", "2026-10-27")
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert len(saved) == 1
    assert saved[0]["multiplier"] is None
    assert saved[0]["vxn"] is None


def test_history_ndx_vs_live_vxn_date_mismatch(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-10-28",
                "ndx": 100.0,
                "ndx_date": "2026-10-27",
                "ath": 120.0,
                "ath_date": "2026-06-01",
            }
        ]
    )
    app, saved = _run(monkeypatch, _unavailable_ndx(), _vxn_payload(DATE), history)
    assert not app.exception
    assert _has_mismatch_warning(app, "2026-10-27", "2026-10-28")
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert not saved


def test_both_history_fallback_dates_differ(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-10-28",
                "ndx": 100.0,
                "ndx_date": "2026-10-26",
                "ath": 120.0,
                "ath_date": "2026-06-01",
                "vxn": 22.0,
                "vxn_date": "2026-10-27",
            }
        ]
    )
    app, saved = _run(
        monkeypatch, _unavailable_ndx(), _unavailable_vxn(), history
    )
    assert not app.exception
    assert any(
        "历史回退日期不一致" in text
        and "2026-10-26" in text
        and "2026-10-27" in text
        for text in _warnings(app)
    )
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert not saved


def test_proxy_ndx_vs_live_vxn_date_mismatch(monkeypatch):
    app, saved = _run(
        monkeypatch,
        _ndx_payload(DATE, proxy=True, current=96.0),
        _vxn_payload("2026-10-27"),
    )
    assert not app.exception
    assert _has_mismatch_warning(app, "2026-10-28", "2026-10-27")
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert not saved


def test_session_fallback_ndx_vs_live_vxn_date_mismatch(monkeypatch):
    state = {"ndx": _ndx_payload(DATE), "vxn": _vxn_payload(DATE)}
    monkeypatch.setattr(helpers, "is_market_data_stale", lambda *a, **k: False)
    monkeypatch.setattr(ndx_mod, "fetch_ndx", lambda period="2y": state["ndx"])
    monkeypatch.setattr(vxn_mod, "fetch_vxn", lambda period="10y": state["vxn"])
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
    monkeypatch.setattr(
        pe_mod,
        "fetch_pe",
        lambda: {
            "value": 30.0,
            "date": TODAY,
            "history": None,
            "source": "test PE",
            "error": None,
            "status": "ok",
            "usable_for_model": True,
        },
    )
    monkeypatch.setattr(
        storage, "load_history_preferred", lambda: (pd.DataFrame(), "test", None)
    )
    saved = []

    def fake_save(row):
        saved.append(row)
        return "test", None

    monkeypatch.setattr(storage, "save_history", fake_save)
    monkeypatch.setattr(
        storage, "migrate_local_csv", lambda: {"rows_read": 0, "rows_uploaded": 0}
    )
    cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    assert app.session_state["last_valid_ndx"]["value"] == 100.0
    saved_before = len(saved)

    state["ndx"] = _unavailable_ndx()
    state["vxn"] = _vxn_payload("2026-10-29")
    cache_data.clear()
    app.run()
    assert not app.exception
    assert _has_mismatch_warning(app, "2026-10-28", "2026-10-29")
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert len(saved) == saved_before


def test_same_date_has_no_mismatch_warning_and_decision_is_unchanged(monkeypatch):
    app, saved = _run(monkeypatch, _ndx_payload(DATE), _vxn_payload(DATE))
    assert not app.exception
    assert not _has_mismatch_warning(app, DATE, DATE)
    assert _metric(app, "最终建议倍数") == "1.50×"
    assert len(saved) == 1 and saved[0]["multiplier"] == 1.5


def test_missing_date_does_not_create_mismatch_warning(monkeypatch):
    app, _saved = _run(
        monkeypatch, _ndx_payload(DATE), _vxn_payload(date=None)
    )
    assert not app.exception
    assert not any("不能视为同一时点" in text for text in _warnings(app))
    assert _metric(app, "最终建议倍数") == "暂不可用"
