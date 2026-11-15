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
FETCHED_AT = "2026-10-29T08:00:00Z"
FETCHED_AT_LABEL = "2026-10-29 16:00:00（台北时间）"
PE_NOTE = "ETF 组合市盈率代理值，不代表官方 Nasdaq-100 指数 PE。"
FGI_NOTE = "美国股票市场情绪参考，不参与 Nasdaq-100 仓位决策。"


def _series(high=120.0, current=100.0, periods=300, end=DATE):
    index = pd.bdate_range(end=pd.Timestamp(end), periods=periods)
    values = [float(high)] * periods
    values[-1] = float(current)
    return pd.Series(values, index=index, dtype=float)


def _ndx_payload():
    return {
        "value": 100.0,
        "date": DATE,
        "updated_at": FETCHED_AT,
        "history": _series(),
        "symbol": "^NDX",
        "source": "test NDX",
        "error": None,
        "proxy": False,
        "is_official": True,
        "status": "ok",
    }


def _vxn_payload():
    return {
        "value": 22.0,
        "date": DATE,
        "updated_at": FETCHED_AT,
        "history": _series(high=22.0, current=22.0, periods=260),
        "source": "test VXN",
        "error": None,
        "proxy": False,
        "is_official": True,
        "status": "ok",
    }


def _fgi_payload(date=DATE, updated_at=FETCHED_AT):
    return {
        "value": 51.0,
        "date": date,
        "updated_at": updated_at,
        "history": None,
        "source": "test FGI",
        "error": None,
    }


def _pe_payload(date=DATE, updated_at=FETCHED_AT):
    return {
        "value": 34.56,
        "date": date,
        "updated_at": updated_at,
        "history": None,
        "source": "BlackRock / iShares IQQ ETF portfolio",
        "error": None,
        "status": "ok",
        "usable_for_model": True,
    }


def _run(monkeypatch, fgi=None, pe=None):
    monkeypatch.setattr(helpers, "is_market_data_stale", lambda *args, **kwargs: False)
    monkeypatch.setattr(ndx_mod, "fetch_ndx", lambda period="2y": _ndx_payload())
    monkeypatch.setattr(vxn_mod, "fetch_vxn", lambda period="10y": _vxn_payload())
    monkeypatch.setattr(fgi_mod, "fetch_fear_greed", lambda: fgi or _fgi_payload())
    monkeypatch.setattr(pe_mod, "fetch_pe", lambda: pe or _pe_payload())
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
    return app, saved


def _metric_values(app, label):
    return [item.value for item in app.metric if item.label == label]


def _metric(app, label):
    values = _metric_values(app, label)
    assert values, f"metric not found: {label}"
    return values[0]


def _captions(app):
    return [item.value for item in app.caption]


def _status_frame(app):
    frames = [item.value for item in app.dataframe]
    return next(
        frame
        for frame in frames
        if "指标" in frame.columns and "保存日期" in frame.columns
    )


def test_pe_score_displays_one_decimal_without_changing_stored_value(monkeypatch):
    app, saved = _run(monkeypatch)
    assert not app.exception

    score_values = _metric_values(app, "评分")
    assert score_values == ["100.0", "46.8"]
    assert all("46.75" not in value for value in score_values)
    assert len(saved) == 1
    assert abs(saved[0]["pe_score"] - 46.75999999999999) < 1e-9


def test_fgi_usage_text_is_short_and_full_note_is_visible(monkeypatch):
    app, _saved = _run(monkeypatch)
    assert not app.exception
    assert _metric(app, "仓位作用") == "仅展示"
    assert any(FGI_NOTE in text for text in _captions(app))
    assert "51" in _metric_values(app, "最新值")


def test_all_indicators_use_date_and_beijing_fetch_time_format(monkeypatch):
    app, _saved = _run(monkeypatch)
    assert not app.exception

    captions = _captions(app)
    for source in ("test NDX", "test VXN", "test FGI", "BlackRock"):
        card = next(text for text in captions if source in text)
        assert "数据日期：2026-10-28" in card
        assert f"本次获取时间：{FETCHED_AT_LABEL}" in card

    status = _status_frame(app)
    assert status["行情日期"].tolist() == [DATE, DATE, DATE, DATE]
    assert status["保存日期"].tolist() == ["—", "—", "—", "—"]
    assert not any("None" in str(value) for value in status["保存日期"])
    assert not any("T" in str(value) for value in status["行情日期"])


def test_pe_status_note_is_concise_and_source_is_preserved(monkeypatch):
    app, _saved = _run(monkeypatch)
    assert not app.exception

    status = _status_frame(app)
    pe_row = status.loc[status["指标"] == "PE"].iloc[0]
    assert pe_row["说明"] == PE_NOTE
    assert pe_row["来源"] == "BlackRock / iShares IQQ ETF portfolio"
    assert "官方 Nasdaq-100 指数 PE" in pe_row["说明"]


def test_invalid_dates_and_fetch_time_fall_back_safely(monkeypatch):
    app, _saved = _run(
        monkeypatch,
        fgi=_fgi_payload(date="not-a-date", updated_at="not-a-time"),
    )
    assert not app.exception

    fgi_caption = next(text for text in _captions(app) if "test FGI" in text)
    assert "数据日期：暂无数据" in fgi_caption
    assert "本次获取时间：暂无数据" in fgi_caption
    assert "2026-10-29" not in fgi_caption

    status = _status_frame(app)
    fgi_row = status.loc[status["指标"] == "FGI"].iloc[0]
    assert fgi_row["行情日期"] == "—"
    assert fgi_row["保存日期"] == "—"


def test_final_multiplier_is_unchanged_by_formatting(monkeypatch):
    app, saved = _run(monkeypatch)
    assert not app.exception
    assert _metric(app, "最终建议倍数") == "1.50×"
    assert len(saved) == 1 and saved[0]["multiplier"] == 1.5
