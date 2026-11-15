import datetime as dt
from pathlib import Path

import pandas as pd
import pytest
from streamlit import cache_data
from streamlit.testing.v1 import AppTest

from config import DRAWDOWN_ZONES
from model import allocation as A
from utils import settings_store

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(scope="module")
def cfg():
    return A.load_config()


def _codes(topup):
    return {fund.code: amount for fund, amount in topup.items}


def expected_topup(cfg, multiplier):
    """The documented rule, written out independently of daily_topup."""
    return A.round_yuan(cfg.base * (multiplier - 1)) if multiplier > 1 else 0


def topup_fund(cfg):
    return min((f for f in cfg.funds if f.topup_priority is not None and not f.paused), key=lambda f: f.topup_priority)


def fixed_funds(cfg):
    return [f for f in cfg.auto_funds if f.topup_priority is None]


def manual_fund(cfg):
    return next(f for f in cfg.funds if f.manual_only)


def test_repo_config_is_consistent(cfg):
    assert cfg.trading_days == 21
    assert cfg.base == sum(f.daily for f in cfg.auto_funds) > 0
    assert all(f.cap is None or f.daily <= f.cap for f in cfg.auto_funds)
    assert fixed_funds(cfg), "the example keeps one fixed, never-topped-up fund"
    assert manual_fund(cfg).paused and manual_fund(cfg).daily == 0
    assert len(cfg.zones) == 3
    assert sum(z.budget for z in cfg.zones) == cfg.ammo_total


def test_auto_invest_is_fixed_and_fixed_funds_never_top_up(cfg):
    fixed = {f.code for f in fixed_funds(cfg)}
    for tier in A.TIERS:
        assert not fixed & set(_codes(A.daily_topup(tier, cfg)))
    assert A.daily_topup(1.0, cfg).total == 0


def test_rounding_is_half_up():
    config = A.Config(funds=[A.Fund("甲", "A", "", 10, None, topup_priority=1)])
    assert A.daily_topup(1.25, config).total == 3  # 2.5 rounds up, not to even


@pytest.mark.parametrize("multiplier", A.TIERS)
def test_daily_topup_goes_to_the_first_priority_fund(cfg, multiplier):
    fund = topup_fund(cfg)
    total = expected_topup(cfg, multiplier)
    assert fund.room is None or fund.room >= expected_topup(cfg, max(A.TIERS))  # example fits in one fund
    top = A.daily_topup(multiplier, cfg)
    assert top.total == total and top.over_cap == 0
    assert _codes(top) == ({fund.code: total} if total else {})


def test_topup_respects_daily_room_and_priority():
    small = A.Fund("甲", "A", "", 20, 50, topup_priority=1)  # room 30
    big = A.Fund("乙", "B", "", 0, 40, topup_priority=2)  # room 40
    config = A.Config(funds=[small, big, A.Fund("丙", "C", "", 80, None)])  # base 100
    top = A.daily_topup(2.0, config)  # needs 100
    assert _codes(top) == {"A": 30, "B": 40} and top.over_cap == 30
    limited = A.daily_topup(2.0, config, limit=25)
    assert _codes(limited) == {"A": 25} and limited.limited_to == 25


@pytest.mark.parametrize("multiplier", A.TIERS)
def test_monthly_draw(cfg, multiplier):
    expected = cfg.base * (multiplier - 1) * cfg.trading_days
    assert A.monthly_draw(multiplier, cfg) == pytest.approx(expected)
    assert A.monthly_draw(1.0, cfg) == 0


def test_ammo_zones_use_the_drawdown_boundary_convention(cfg):
    assert A.ammo_zone(-0.05, cfg) is None
    assert A.ammo_zone(-0.08, cfg).key == "z1"
    assert A.ammo_zone(-0.249, cfg).key == "z1"
    assert A.ammo_zone(-0.25, cfg).key == "z2"
    assert A.ammo_zone(-0.35, cfg).key == "z3"
    assert A.ammo_zone(-0.70, cfg).key == "z3"
    # ammo zone edges line up with the multiplier zones
    starts = {z["key"]: z["max_dd"] for z in DRAWDOWN_ZONES}
    assert cfg.zones[0].from_dd == starts["mild"] and cfg.zones[1].from_dd == starts["extreme"]


def test_ammo_status_and_exhaustion(cfg):
    z1, z2 = cfg.zones[0].budget, cfg.zones[1].budget
    need = expected_topup(cfg, 1.5)
    monthly = A.monthly_draw(1.5, cfg)

    fresh = A.ammo_status(-0.15, 1.5, cfg, {"balance": cfg.ammo_total, "used": {}})
    assert fresh["zone"].key == "z1" and fresh["remaining"] == z1
    assert fresh["effective"] == 1.5 and fresh["monthly"] == pytest.approx(monthly)
    assert fresh["months_left"] == pytest.approx(z1 / monthly)
    assert A.topup_for(fresh, cfg).total == need

    rest = cfg.ammo_total - z1
    spent = A.ammo_status(-0.15, 1.5, cfg, {"balance": rest, "used": {"z1": z1}})
    assert spent["exhausted"] and spent["effective"] == 1.0 and spent["monthly"] == 0
    assert A.topup_for(spent, cfg).total == 0

    short = need // 2
    assert 0 < short < need
    nearly = A.ammo_status(-0.15, 1.5, cfg, {"balance": rest, "used": {"z1": z1 - short}})
    top = A.topup_for(nearly, cfg)
    assert top.total == short and top.limited_to == short and top.needed == need

    # the next zone has its own budget again
    deeper = A.ammo_status(-0.28, 2.5, cfg, {"balance": rest, "used": {"z1": z1}})
    assert not deeper["exhausted"] and deeper["remaining"] == z2

    low = A.ammo_status(-0.15, 2.0, cfg, {"balance": 500, "used": {}})
    assert low["short_of_balance"] and low["months_left"] == pytest.approx(500 / A.monthly_draw(2.0, cfg))

    calm = A.ammo_status(-0.03, 1.0, cfg, {})
    assert calm["zone"] is None and calm["monthly"] == 0 and not calm["recorded"]


def test_checkpoints():
    assert A.checkpoint(-0.03, 1.0) is None
    assert A.checkpoint(-0.15, 1.5) == "1.50×"
    assert A.checkpoint(-0.40, 3.0) == "3.00×"
    assert A.checkpoint(-0.45, 3.0) == "-45%"
    assert A.checkpoint(-0.60, 2.5) == "-55%"


def test_malformed_config_raises(tmp_path):
    bad = tmp_path / "funds.yaml"
    bad.write_text("funds:\n  - daily: 10\n", encoding="utf-8")
    with pytest.raises(ValueError):
        A.load_config(bad)
    bad.write_text("funds: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        A.load_config(bad)


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "LOCAL_PATH", tmp_path / "s.json")
    monkeypatch.setattr(settings_store.database, "get_supabase_client", lambda: None)
    return tmp_path


def test_ammo_store_and_manual_topups(local_store):
    assert settings_store.get_ammo()["state"] == {}
    backend, error = settings_store.set_ammo(1000, {"z1": 100})
    assert backend == "Local file" and error is None
    state = settings_store.get_ammo()["state"]
    assert state["balance"] == 1000 and state["used"] == {"z1": 100}

    settings_store.record_manual(state, "1.50×", 300, "z1", "2026-11-16")
    state = settings_store.get_ammo()["state"]
    assert state["balance"] == 700 and state["used"]["z1"] == 400
    assert state["manual"]["1.50×"]["amount"] == 300
    with pytest.raises(ValueError):
        settings_store.record_manual(state, "1.50×", 100, "z1", "2026-11-17")

    settings_store.undo_manual(state, "1.50×")
    state = settings_store.get_ammo()["state"]
    assert state["balance"] == 1000 and state["used"]["z1"] == 100 and state["manual"] == {}

    booked, backend, _ = settings_store.book_topup(state, "z1", 35, "2026-11-16")
    assert booked and backend == "Local file"
    state = settings_store.get_ammo()["state"]
    assert state["balance"] == 965 and state["used"]["z1"] == 135
    assert settings_store.book_topup(state, "z1", 35, "2026-11-16")[0] is False  # once per day
    assert settings_store.book_topup(state, "z1", 0, "2026-11-17")[0] is False
    settings_store.set_ammo(100, {}, {}, state["last_auto"])
    assert settings_store.get_ammo()["state"]["last_auto"]["date"] == "2026-11-16"
    assert settings_store.book_topup({}, "z1", 35, "2026-11-18")[0] is False  # no balance recorded

    with pytest.raises(ValueError):
        settings_store.set_ammo(-1, {})
    with pytest.raises(ValueError):
        settings_store.set_ammo(10, {"z1": -5})


def test_days_since():
    now = dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc)
    assert settings_store.days_since("2026-10-01T00:00:00+00:00", now) == 44
    assert settings_store.days_since(None, now) is None


# ---- app: lock / unlock ----------------------------------------------------

def _run_app(monkeypatch, tmp_path, secrets=None):
    import data_sources.fear_greed as fgi_mod
    import data_sources.ndx as ndx_mod
    import data_sources.valuation as pe_mod
    import data_sources.vxn as vxn_mod
    import utils.storage as storage_mod
    from utils import helpers

    index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=300)
    series = pd.Series([120.0] * 299 + [100.0], index=index)  # -16.7% -> 1.5x with VXN 22
    vxn_series = pd.Series([22.0] * 300, index=index)
    day = index[-1].date().isoformat()
    monkeypatch.setattr(helpers, "is_market_data_stale", lambda *a, **k: False)
    monkeypatch.setattr(
        ndx_mod,
        "fetch_ndx",
        lambda period="max": {"value": 100.0, "date": day, "history": series, "source": "t", "proxy": False,
                              "status": "ok", "updated_at": "2026-11-14T00:00:00Z", "error": None},
    )
    monkeypatch.setattr(
        vxn_mod,
        "fetch_vxn",
        lambda period="10y": {"value": 22.0, "date": day, "history": vxn_series, "source": "t",
                              "status": "ok", "updated_at": "2026-11-14T00:00:00Z", "error": None},
    )
    monkeypatch.setattr(fgi_mod, "fetch_fear_greed", lambda: {"value": 50.0, "date": day, "source": "t"})
    monkeypatch.setattr(pe_mod, "fetch_pe", lambda: {"value": 30.0, "date": day, "source": "t", "status": "ok"})
    monkeypatch.setattr(storage_mod, "load_history_preferred", lambda: (pd.DataFrame(), "test", None))
    monkeypatch.setattr(storage_mod, "save_history", lambda row: ("test", None))
    monkeypatch.setattr(settings_store, "LOCAL_PATH", tmp_path / "s.json")
    monkeypatch.setattr(settings_store.database, "get_supabase_client", lambda: None)
    settings_store.set_ammo(1000, {"z1": 0})
    cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=30)
    for key, value in (secrets or {}).items():
        app.secrets[key] = value
    return app.run()


def _html(app):
    return " ".join(str(el.proto.body) for el in app.get("html"))


def _topup_text():
    return f"加 ¥{expected_topup(A.load_config(), 1.5):,.0f}"


def test_money_is_visible_without_access_code(monkeypatch, tmp_path):
    cfg = A.load_config()
    app = _run_app(monkeypatch, tmp_path)  # -16.7% with VXN 22 -> 1.5x, ammo balance 1000
    assert not app.exception
    body = _html(app)
    assert _topup_text() in body and topup_fund(cfg).code in body
    assert "自动定投 · 固定" in body
    for fund in fixed_funds(cfg):
        assert f"{fund.code} ¥{fund.daily:,.0f}" in body
    assert f"约可撑 {1000 / A.monthly_draw(1.5, cfg):.1f} 个月" in body and "余额少于本区剩余额度" in body
    assert "还可以额外补仓一次" in body and manual_fund(cfg).code in body
    assert "还没有往日记录" in body


def test_money_is_locked_until_code_entered(monkeypatch, tmp_path):
    app = _run_app(monkeypatch, tmp_path, secrets={"access_code": "s3cret"})
    assert not app.exception
    assert _topup_text() not in _html(app)
    assert "¥1,000" not in _html(app)

    app.text_input(key="access_attempt").input("wrong")
    next(b for b in app.button if b.label == "解锁").click().run()
    assert _topup_text() not in _html(app)
    assert any("口令不正确" in e.value for e in app.error)

    app.text_input(key="access_attempt").input("s3cret")
    next(b for b in app.button if b.label == "解锁").click().run()
    assert _topup_text() in _html(app)
