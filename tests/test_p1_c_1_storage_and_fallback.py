from pathlib import Path

import pandas as pd
from streamlit import cache_data
from streamlit.testing.v1 import AppTest

import data_sources.fear_greed as fgi_mod
import data_sources.ndx as ndx_mod
import data_sources.valuation as pe_mod
import data_sources.vxn as vxn_mod
import utils.database as database
import utils.storage as storage
from utils import helpers

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
DATE = "2026-10-28"
TODAY = pd.Timestamp.today().date().isoformat()
MIGRATION_ROWS = [
    {"date": "2026-08-28", "ndx": 100.0},
    {"date": "2026-08-29", "ndx": 101.0},
    {"date": "2026-08-30", "ndx": 102.0},
]


def _write_history(tmp_path, rows):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(data_dir / "history.csv", index=False)


def _storage_result(tmp_path, monkeypatch, fail_dates=(), unavailable=False):
    _write_history(tmp_path, MIGRATION_ROWS)
    monkeypatch.setattr(storage, "PROJECT_ROOT", tmp_path)
    if unavailable:
        monkeypatch.setattr(
            storage.database, "test_connection", lambda: {"ok": False, "error": "offline"}
        )
        monkeypatch.setattr(
            storage.database,
            "upsert_snapshot",
            lambda record: (_ for _ in ()).throw(AssertionError("must not upsert")),
        )
    else:
        monkeypatch.setattr(
            storage.database, "test_connection", lambda: {"ok": True, "error": None}
        )

        def fake_upsert(record):
            if record.get("date") in fail_dates:
                raise RuntimeError(f"boom {record.get('date')}")

        monkeypatch.setattr(storage.database, "upsert_snapshot", fake_upsert)
    return storage.migrate_local_csv()


def test_migrate_all_success_keeps_fields_and_empty_failed_rows(tmp_path, monkeypatch):
    result = _storage_result(tmp_path, monkeypatch)
    assert result["rows_read"] == 3
    assert result["rows_uploaded"] == 3
    assert result["rows_failed"] == 0
    assert result["error"] is None
    assert result["failed_rows"] == []


def test_migrate_partial_failure_reports_date_and_exception(tmp_path, monkeypatch):
    result = _storage_result(tmp_path, monkeypatch, fail_dates={"2026-08-29"})
    assert result["rows_read"] == 3
    assert result["rows_uploaded"] == 2
    assert result["rows_failed"] == 1
    assert result["error"] == "Some rows failed"
    assert result["failed_rows"] == [
        {"row": 3, "date": "2026-08-29", "error": "RuntimeError: boom 2026-08-29"}
    ]


def test_migrate_all_failure_reports_every_row(tmp_path, monkeypatch):
    result = _storage_result(
        tmp_path, monkeypatch, fail_dates={"2026-08-28", "2026-08-29", "2026-08-30"}
    )
    assert result["rows_read"] == 3
    assert result["rows_uploaded"] == 0
    assert result["rows_failed"] == 3
    assert len(result["failed_rows"]) == 3
    assert [item["date"] for item in result["failed_rows"]] == [
        "2026-08-28",
        "2026-08-29",
        "2026-08-30",
    ]
    assert all("RuntimeError" in item["error"] for item in result["failed_rows"])


def test_migrate_unavailable_reports_all_rows_without_losing_reason(tmp_path, monkeypatch):
    result = _storage_result(tmp_path, monkeypatch, unavailable=True)
    assert result["rows_uploaded"] == 0
    assert result["rows_failed"] == 3
    assert result["error"] == "Supabase unavailable"
    assert len(result["failed_rows"]) == 3
    assert all(item["error"] == "Supabase unavailable" for item in result["failed_rows"])


def test_migrate_missing_date_has_row_identifier(tmp_path, monkeypatch):
    _write_history(
        tmp_path,
        [
            {"date": "2026-08-28", "ndx": 100.0},
            {"date": None, "ndx": 101.0},
        ],
    )
    monkeypatch.setattr(storage, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        storage.database, "test_connection", lambda: {"ok": True, "error": None}
    )

    def fake_upsert(record):
        if record.get("date") is None:
            raise ValueError("missing date")

    monkeypatch.setattr(storage.database, "upsert_snapshot", fake_upsert)
    result = storage.migrate_local_csv()
    assert result["failed_rows"] == [
        {"row": 3, "date": None, "error": "ValueError: missing date"}
    ]


class FakeResponse:
    def __init__(self, data=None):
        self.data = data


class FakeQuery:
    def __init__(self, client):
        self.client = client

    def select(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def upsert(self, record, on_conflict=None):
        date = record.get("date")
        if date in self.client.fail_dates:
            raise RuntimeError(f"upsert failed for {date}")
        self.client.upserted.append(date)
        return self

    def execute(self):
        return FakeResponse([])


class FakeClient:
    def __init__(self, fail_dates=()):
        self.fail_dates = set(fail_dates)
        self.upserted = []

    def table(self, name):
        return FakeQuery(self)


def _run_app(monkeypatch, tmp_path, fail_dates=(), history=None):
    _write_history(tmp_path, MIGRATION_ROWS)
    monkeypatch.setattr(storage, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(helpers, "is_market_data_stale", lambda *args, **kwargs: False)
    monkeypatch.setattr(ndx_mod, "fetch_ndx", lambda period="2y": _ndx_payload())
    monkeypatch.setattr(vxn_mod, "fetch_vxn", lambda period="10y": _vxn_payload())
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
    monkeypatch.setattr(storage, "save_history", lambda row: ("test", None))
    client = FakeClient(fail_dates=fail_dates)
    monkeypatch.setattr(database, "get_supabase_client", lambda: client)
    cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    return app


def _click_migration(app):
    button = next(b for b in app.button if b.label == "迁移本地 CSV 到 Supabase")
    button.click().run()
    return app


def _texts(elements):
    return [element.value for element in elements]


def _failure_frames(app):
    return [frame.value for frame in app.dataframe if "CSV行号" in frame.value.columns]


def test_app_partial_migration_shows_counts_and_failed_date(tmp_path, monkeypatch):
    app = _run_app(monkeypatch, tmp_path, fail_dates={"2026-08-29"})
    _click_migration(app)
    assert not app.exception
    assert any(
        "读取 3 行，成功 2 行，失败 1 行" in text for text in _texts(app.warning)
    )
    assert not any(text.startswith("读取") for text in _texts(app.success))
    frames = _failure_frames(app)
    assert len(frames) == 1
    row = frames[0].iloc[0]
    assert row["日期"] == "2026-08-29"
    assert "RuntimeError" in row["错误"]


def test_app_all_success_migration_has_no_failure_table(tmp_path, monkeypatch):
    app = _run_app(monkeypatch, tmp_path)
    _click_migration(app)
    assert not app.exception
    assert any("读取 3 行，上传 3 行。" in text for text in _texts(app.success))
    assert not _failure_frames(app)
    assert not any("失败" in text for text in _texts(app.warning))


def test_app_all_failure_migration_uses_error_not_success(tmp_path, monkeypatch):
    app = _run_app(
        monkeypatch,
        tmp_path,
        fail_dates={"2026-08-28", "2026-08-29", "2026-08-30"},
    )
    _click_migration(app)
    assert not app.exception
    assert any(
        "读取 3 行，成功 0 行，失败 3 行" in text for text in _texts(app.error)
    )
    assert not any(text.startswith("读取") for text in _texts(app.success))
    frames = _failure_frames(app)
    assert len(frames) == 1
    assert set(frames[0]["日期"]) == {"2026-08-28", "2026-08-29", "2026-08-30"}


def _series(high=120.0, current=100.0, periods=300):
    index = pd.bdate_range(end=pd.Timestamp(DATE), periods=periods)
    values = [float(high)] * periods
    values[-1] = float(current)
    return pd.Series(values, index=index, dtype=float)


def _ndx_payload():
    return {
        "value": 100.0,
        "date": DATE,
        "updated_at": "2026-10-29T08:00:00Z",
        "history": _series(),
        "symbol": "^NDX",
        "source": "Yahoo Finance (^NDX)",
        "error": None,
        "proxy": False,
        "is_official": True,
        "status": "ok",
    }


def _vxn_payload():
    return {
        "value": 22.0,
        "date": DATE,
        "updated_at": "2026-10-29T08:00:00Z",
        "history": pd.Series(
            [22.0] * 260, index=pd.bdate_range(end=pd.Timestamp(DATE), periods=260)
        ),
        "source": "Yahoo Finance (^VXN)",
        "error": None,
        "proxy": False,
        "is_official": True,
        "status": "ok",
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


def _run_history(monkeypatch, history):
    monkeypatch.setattr(ndx_mod, "fetch_ndx", lambda period="2y": _unavailable_ndx())
    monkeypatch.setattr(vxn_mod, "fetch_vxn", lambda period="10y": _unavailable_vxn())
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
        storage, "load_history_preferred", lambda: (history, "test", None)
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


def _captions(app):
    return [item.value for item in app.caption]


def test_future_ndx_history_date_is_rejected(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-09-01",
                "ndx": 100.0,
                "ndx_date": "2026-12-31",
                "ath": 120.0,
                "ath_date": "2026-06-01",
                "vxn": 22.0,
                "vxn_date": "2026-08-28",
            }
        ]
    )
    app, saved = _run_history(monkeypatch, history)
    assert not app.exception
    assert _metric(app, "距高点回撤") == "暂无数据"
    assert not any("2026-12-31" in text for text in _captions(app))
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert not saved


def test_future_vxn_history_date_is_rejected(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-09-01",
                "ndx": 100.0,
                "ndx_date": "2026-08-28",
                "ath": 120.0,
                "ath_date": "2026-06-01",
                "vxn": 22.0,
                "vxn_date": "2026-12-31",
            }
        ]
    )
    app, saved = _run_history(monkeypatch, history)
    assert not app.exception
    assert not any("2026-12-31" in text for text in _captions(app))
    assert any("2026-08-28" in text for text in _captions(app))
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert not saved


def test_ndx_market_date_later_than_save_date_is_rejected(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-08-01",
                "ndx": 100.0,
                "ndx_date": "2026-08-02",
                "ath": 120.0,
                "ath_date": "2026-06-01",
                "vxn": 22.0,
                "vxn_date": "2026-08-01",
            }
        ]
    )
    app, saved = _run_history(monkeypatch, history)
    assert not app.exception
    assert not any("2026-08-02" in text for text in _captions(app))
    assert _metric(app, "距高点回撤") == "暂无数据"
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert not saved


def test_vxn_market_date_later_than_save_date_is_rejected(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-08-01",
                "ndx": 100.0,
                "ndx_date": "2026-08-01",
                "ath": 120.0,
                "ath_date": "2026-06-01",
                "vxn": 22.0,
                "vxn_date": "2026-08-02",
            }
        ]
    )
    app, saved = _run_history(monkeypatch, history)
    assert not app.exception
    assert not any("2026-08-02" in text for text in _captions(app))
    assert any("2026-08-01" in text for text in _captions(app))
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert not saved


def test_stale_history_is_explicitly_labeled(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "ndx": 100.0,
                "ndx_date": "2025-01-02",
                "ath": 120.0,
                "ath_date": "2024-06-01",
                "vxn": 22.0,
                "vxn_date": "2025-01-02",
            }
        ]
    )
    app, saved = _run_history(monkeypatch, history)
    assert not app.exception
    assert any("历史数据已过期" in text for text in _texts(app.warning))
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert not saved


def test_cross_metric_history_dates_are_shown_and_flagged(monkeypatch):
    history = pd.DataFrame(
        [
            {
                "date": "2026-09-01",
                "ndx": 100.0,
                "ndx_date": "2026-08-27",
                "ath": 120.0,
                "ath_date": "2026-06-01",
                "vxn": 20.0,
                "vxn_date": "2026-08-29",
            },
            {
                "date": "2026-09-02",
                "ndx": 105.0,
                "ndx_date": "2026-08-28",
                "ath": 125.0,
                "ath_date": "2026-06-01",
                "vxn": 30.0,
                "vxn_date": "2026-08-27",
            },
        ]
    )
    app, saved = _run_history(monkeypatch, history)
    assert not app.exception
    captions = _captions(app)
    ndx_caption = next(text for text in captions if "Yahoo Finance (^NDX)" in text and "历史保存" in text)
    vxn_caption = next(text for text in captions if "Yahoo Finance (^VXN)" in text and "历史保存" in text)
    assert "行情日期 2026-08-28" not in ndx_caption  # caption uses 数据日期
    assert "数据日期：2026-08-28" in ndx_caption
    assert "数据日期：2026-08-29" in vxn_caption
    assert any(
        "历史回退日期不一致" in text
        and "2026-08-28" in text
        and "2026-08-29" in text
        for text in _texts(app.warning)
    )
    assert _metric(app, "最终建议倍数") == "暂不可用"
    assert not saved
