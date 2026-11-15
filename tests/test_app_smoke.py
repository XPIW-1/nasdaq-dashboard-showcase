import pandas as pd
from pathlib import Path


def test_streamlit_app_smoke(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import data_sources.ndx as ndx_mod
    import data_sources.vxn as vxn_mod
    import data_sources.fear_greed as fgi_mod
    import data_sources.valuation as pe_mod
    import utils.storage as storage_mod

    idx = pd.date_range("2025-09-01", periods=260, freq="B")
    ndx_series = pd.Series(range(20000, 20260), index=idx, dtype=float)
    vxn_series = pd.Series([20.0] * 260, index=idx)
    monkeypatch.setattr(ndx_mod, "fetch_ndx", lambda period="2y": {"value": 20200.0, "date": "2026-08-28", "updated_at": "2026-08-28T22:00:00Z", "history": ndx_series, "symbol": "^NDX", "source": "test", "error": None})
    monkeypatch.setattr(vxn_mod, "fetch_vxn", lambda period="10y": {"value": 22.0, "date": "2026-08-28", "updated_at": "2026-08-28T22:00:00Z", "history": vxn_series, "source": "test", "error": None})
    monkeypatch.setattr(fgi_mod, "fetch_fear_greed", lambda: {"value": 50.0, "date": "2026-08-28", "updated_at": "2026-08-28T22:00:00Z", "history": None, "source": "test", "error": None})
    monkeypatch.setattr(pe_mod, "fetch_pe", lambda: {"value": 30.0, "date": "2026-08-28", "updated_at": "2026-08-28T22:00:00Z", "history": None, "source": "test", "error": None})
    monkeypatch.setattr(storage_mod, "load_history_preferred", lambda: (pd.DataFrame(), "test", None))
    monkeypatch.setattr(storage_mod, "save_history", lambda row: ("test", None))
    monkeypatch.setattr(storage_mod, "migrate_local_csv", lambda: {"rows_read": 0, "rows_uploaded": 0})
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert not app.exception
    assert any("最终建议倍数" in x.label for x in app.metric)
