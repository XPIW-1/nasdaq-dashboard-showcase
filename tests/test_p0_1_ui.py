import datetime as dt
import math
from pathlib import Path

import pandas as pd
from streamlit import cache_data
from streamlit.testing.v1 import AppTest

import data_sources.fear_greed as fgi_mod
import data_sources.ndx as ndx_mod
import data_sources.valuation as pe_mod
import data_sources.vxn as vxn_mod
import utils.storage as storage_mod
from model.signals import calculate_drawdown
from utils import helpers

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
TODAY = dt.date.today().isoformat()


def _series(high=120.0, current=100.0, periods=260):
    index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=periods)
    values = [float(high)] * periods
    values[-1] = float(current)
    return pd.Series(values, index=index, dtype=float)


def _ndx_payload(series, value=None, *, proxy=False, status="ok", error=None):
    ordered = series.sort_index() if series is not None and len(series) else None
    return {
        "value": float(ordered.iloc[-1]) if value is None and ordered is not None else value,
        "date": ordered.index[-1].date().isoformat() if ordered is not None else None,
        "updated_at": "2026-10-29T07:00:00Z" if status in ("ok", "proxy") else None,
        "history": series,
        "symbol": "QQQ" if proxy else "^NDX",
        "source": "Yahoo Finance QQQ（Nasdaq-100 代理）" if proxy else "test ^NDX",
        "error": error,
        "proxy": proxy,
        "status": "proxy" if proxy else status,
    }


def _vxn_payload(value=22.0, series=None, *, status="ok", error=None):
    if series is None and value is not None and math.isfinite(float(value)):
        index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=260)
        series = pd.Series([float(value)] * 260, index=index)
    return {
        "value": value,
        "date": series.index[-1].date().isoformat() if series is not None and len(series) else None,
        "updated_at": "2026-10-29T07:00:00Z" if status == "ok" else None,
        "history": series,
        "source": "test ^VXN",
        "error": error,
        "proxy": False,
        "status": status,
    }


def _run(monkeypatch, ndx, vxn, history=None):
    monkeypatch.setattr(helpers, "is_market_data_stale", lambda *args, **kwargs: False)
    monkeypatch.setattr(ndx_mod, "fetch_ndx", lambda period="2y": ndx)
    monkeypatch.setattr(vxn_mod, "fetch_vxn", lambda period="10y": vxn)
    monkeypatch.setattr(
        fgi_mod,
        "fetch_fear_greed",
        lambda: {
            "value": 50.0,
            "date": TODAY,
            "updated_at": "2026-10-29T07:00:00Z",
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
            "updated_at": "2026-10-29T07:00:00Z",
            "history": None,
            "source": "test PE",
            "error": None,
            "status": "ok",
            "usable_for_model": True,
        },
    )
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
    for item in app.metric:
        if item.label == label:
            return item.value
    raise AssertionError(f"metric not found: {label}")


def _texts(elements):
    return [element.value for element in elements]


def test_manual_ndx_override_never_splices_with_fetched_history(monkeypatch):
    app, saved = _run(monkeypatch, _ndx_payload(_series()), _vxn_payload(22.0))
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "1.50×"
    saved_before = len(saved)

    app.checkbox[0].check().run()
    ndx_input = next(item for item in app.number_input if item.label == "手动 Nasdaq-100")
    ndx_input.set_value(90.0).run()

    assert not app.exception
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert _metric(app, "回撤状态") == "暂无数据"
    assert _metric(app, "当前 Nasdaq-100") == "90.00"
    assert _metric(app, "历史最高收盘价") == "暂无数据"
    assert len(saved) == saved_before
    assert any("缺少可校验的历史序列" in text for text in _texts(app.warning))


def test_manual_vxn_invalid_does_not_overwrite_cache_or_upgrade(monkeypatch):
    app, saved = _run(monkeypatch, _ndx_payload(_series()), _vxn_payload(22.0))
    assert app.session_state["last_valid_vxn"]["value"] == 22.0

    invalid_vxn = _vxn_payload(float("nan"), status="invalid", error="bad vxn")
    monkeypatch.setattr(vxn_mod, "fetch_vxn", lambda period="10y": invalid_vxn)
    cache_data.clear()
    app.run()
    assert not app.exception
    assert app.session_state["last_valid_vxn"]["value"] == 22.0
    saved_before = len(saved)

    app.checkbox[0].check().run()
    vxn_input = next(item for item in app.number_input if item.label == "手动 VXN")
    vxn_input.set_value(0.0).run()

    assert not app.exception
    assert app.session_state["last_valid_vxn"]["value"] == 22.0
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert _metric(app, "VXN 恐慌级别") == "暂无数据"
    assert len(saved) == saved_before
    assert not app.success


def test_history_ath_date_after_ndx_date_is_not_used(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-09-01",
                "ndx": 100.0,
                "ndx_date": "2026-08-28",
                "ath": 120.0,
                "ath_date": "2026-09-10",
                "vxn": 22.0,
                "vxn_date": "2026-08-28",
            }
        ]
    )
    app, saved = _run(
        monkeypatch,
        _ndx_payload(None, value=None, status="unavailable", error="offline"),
        _vxn_payload(22.0),
        history=history,
    )
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert _metric(app, "回撤状态") == "暂无数据"
    assert _metric(app, "历史最高收盘价") == "暂无数据"
    assert not saved
    assert not any("历史数据回退" in text for text in _texts(app.warning))


def test_history_high_below_current_is_safe(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-09-01",
                "ndx": 400.0,
                "ndx_date": "2026-08-31",
                "ath": 350.0,
                "ath_date": "2026-06-01",
                "vxn": 22.0,
                "vxn_date": "2026-08-31",
            }
        ]
    )
    assert calculate_drawdown(400.0, 350.0) is None
    app, saved = _run(
        monkeypatch,
        _ndx_payload(None, value=None, status="unavailable", error="offline"),
        _vxn_payload(22.0),
        history=history,
    )
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert _metric(app, "回撤状态") == "暂无数据"
    assert _metric(app, "历史最高收盘价") == "暂无数据"
    assert not saved


def test_qqq_proxy_labels_are_consistent(monkeypatch):
    proxy_series = _series(high=120.0, current=96.0)
    app, saved = _run(
        monkeypatch,
        _ndx_payload(proxy_series, proxy=True),
        _vxn_payload(22.0),
    )
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert _metric(app, "当前 Nasdaq-100（QQQ 代理）") == "96.00"

    subheaders = _texts(app.subheader)
    assert "Nasdaq-100 回撤（QQQ 代理）" in subheaders

    usage = _metric(app, "情绪调整用途")
    assert "QQQ 代理参考计算" in usage
    assert "已参与升档判断" not in usage

    captions = _texts(app.caption)
    assert any("QQQ 代理数据推算" in text and "不是官方 NDX 信号" in text for text in captions)
    infos = " ".join(_texts(app.info))
    assert "代理参考" in infos
    assert "不作为官方指数最终信号" in infos
    markdown = " ".join(_texts(app.markdown))
    assert "QQQ 代理参考" in markdown

    status = app.dataframe[0].value
    ndx_row = status.loc[status["指标"] == "Nasdaq-100"].iloc[0]
    assert ndx_row["状态"] == "QQQ 代理数据"
    assert not saved


def test_proxy_with_vxn_fallback_does_not_claim_vxn_reference(monkeypatch):
    history = pd.DataFrame(
        [{"date": "2026-09-01", "vxn": 30.0, "vxn_date": "2026-08-28"}]
    )
    app, saved = _run(
        monkeypatch,
        _ndx_payload(_series(high=120.0, current=96.0), proxy=True),
        _vxn_payload(None, status="unavailable", error="offline"),
        history=history,
    )
    assert not app.exception
    usage = _metric(app, "情绪调整用途")
    assert usage == "仅展示，未用于正式 NDX 升档"
    assert "QQQ 代理参考计算" not in usage
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert not saved


def test_next_trigger_text_does_not_repeat_threshold(monkeypatch):
    app, _saved = _run(monkeypatch, _ndx_payload(_series()), _vxn_payload(22.0))
    messages = [text for text in _texts(app.markdown) if text.startswith("下一档：")]
    assert len(messages) == 1
    message = messages[0]
    assert "回撤达到 -18%" in message
    assert "（进入 2.00×深度回撤）" in message
    assert "（进入 18%" not in message
