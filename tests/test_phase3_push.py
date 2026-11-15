import datetime as dt

import pandas as pd
import pytest

from model import allocation as A
from model.decision import decide
from push.message import fmt_multiplier
from push import daily_push, serverchan
from push.message import build_title
from push.trading_calendar import is_trading_day
from utils import helpers, settings_store

DAY = "2026-11-13"


def _ndx(current=100.0, high=120.0, proxy=False, periods=300):
    index = pd.bdate_range(end=pd.Timestamp(DAY), periods=periods)
    series = pd.Series([high] * (periods - 1) + [current], index=index)
    return {"value": current, "date": DAY, "history": series, "proxy": proxy, "source": "t"}


def _vxn(value=22.0):
    return {"value": value, "date": DAY, "status": "ok", "source": "t"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(helpers, "is_market_data_stale", lambda *a, **k: False)
    import model.decision as decision_mod

    monkeypatch.setattr(decision_mod, "is_market_data_stale", lambda *a, **k: False)


# ---- decision ---------------------------------------------------------------

@pytest.mark.parametrize(
    "current, vxn, expected",
    [(100.0, 22.0, 1.5), (100.0, 36.0, 2.0), (118.0, 50.0, 1.0), (85.0, 41.0, 2.5)],
)
def test_headless_decision_matches_rules(current, vxn, expected):
    result = decide(_ndx(current), _vxn(vxn))
    assert result["kind"] == "final"
    assert result["multiplier"] == expected


def test_proxy_and_missing_vxn_are_not_final():
    assert decide(_ndx(proxy=True), _vxn())["kind"] == "proxy"
    assert decide(_ndx(), {"value": None})["kind"] == "base_only"


def test_stale_or_inconsistent_ndx_is_unavailable(monkeypatch):
    bad = _ndx()
    bad["value"] = 99.0  # does not match the end of the history
    result = decide(bad, _vxn())
    assert result["kind"] == "unavailable" and result["multiplier"] is None
    assert any("不一致" in issue for issue in result["issues"])

    import model.decision as decision_mod

    monkeypatch.setattr(decision_mod, "is_market_data_stale", lambda *a, **k: True)
    assert decide(_ndx(), _vxn())["kind"] == "unavailable"


def test_short_history_uses_all_available_history_like_the_app():
    # The app takes the high over the whole cleaned history (window = length).
    assert decide(_ndx(periods=100), _vxn())["multiplier"] == 1.5


# ---- calendar / title / endpoint --------------------------------------------

def test_a_share_calendar():
    pytest.importorskip("chinese_calendar")
    assert is_trading_day(dt.date(2026, 10, 1))[0] is False  # National Day
    assert is_trading_day(dt.date(2026, 10, 10))[0] is False  # make-up Saturday
    assert is_trading_day(dt.date(2026, 11, 16))[0] is True


def _cfg():
    return A.load_config()


def _topup_fund():
    cfg = _cfg()
    return min((f for f in cfg.funds if f.topup_priority is not None and not f.paused), key=lambda f: f.topup_priority)


def _amount(m):
    cfg = _cfg()
    return A.round_yuan(cfg.base * (m - 1)) if m > 1 else 0


def test_titles():
    cfg = _cfg()
    code = _topup_fund().code
    one = decide(_ndx(118.0), _vxn())
    assert build_title(one, A.daily_topup(1.0, cfg), None) == "纳指 1.0× · 今日无需加仓"
    mid = decide(_ndx(100.0), _vxn())
    assert build_title(mid, A.daily_topup(1.5, cfg), None) == f"纳指 1.5× · 加仓 {code} ¥{_amount(1.5):,.0f}"
    deep = decide(_ndx(100.0), _vxn(36.0))
    title = build_title(deep, A.daily_topup(2.0, cfg), "up", 1.5)
    assert title == f"换档 1.5→2.0× · 每日加仓¥{_amount(2.0):,.0f}"
    assert len(title) <= serverchan.TITLE_LIMIT
    spent = {"exhausted": True}
    assert build_title(mid, A.daily_topup(1.0, cfg), None, ammo=spent) == "纳指 1.5× · 本区弹药用完 今日不加仓"
    bad = decide({"value": None}, _vxn())
    assert build_title(bad, None, None) == "⚠ 数据异常 · 请打开仪表盘核对"


def test_serverchan_endpoints():
    assert serverchan.endpoint("SCT123abc") == "https://sctapi.ftqq.com/SCT123abc.send"
    assert serverchan.endpoint("sctp4567tABC") == "https://4567.push.ft07.com/send/sctp4567tABC.send"
    with pytest.raises(ValueError):
        serverchan.endpoint("")


# ---- runner -----------------------------------------------------------------

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "LOCAL_PATH", tmp_path / "s.json")
    monkeypatch.setattr(settings_store.database, "get_supabase_client", lambda: None)
    settings_store.set_ammo(_cfg().ammo_total, {})
    return tmp_path


def _run(day, current=100.0, vxn=22.0, **kwargs):
    sent, log = [], []
    status = daily_push.run(
        today=day,
        fetch=lambda: (_ndx(current), _vxn(vxn), {"value": 30.0, "status": "ok"}),
        send=lambda title, body: sent.append((title, body)),
        out=log.append,
        **kwargs,
    )
    return status, sent, log


def test_runner_skips_non_trading_day(store):
    status, sent, _ = _run(dt.date(2026, 10, 1))
    assert status == "skipped" and not sent


def test_runner_sends_once_records_state_and_books_ammo(store):
    cfg = _cfg()
    fund, need, z1 = _topup_fund(), _amount(1.5), cfg.zones[0]
    monthly = A.monthly_draw(1.5, cfg)
    monday = dt.date(2026, 11, 16)
    status, sent, log = _run(monday)
    assert status == "sent" and sent[0][0] == f"纳指 1.5× · 加仓 {fund.code} ¥{need:,.0f}"
    body = sent[0][1]
    assert f"**今日手动加仓 ¥{need:,.0f}**" in body
    assert f"{fund.label}（{fund.platform}）：加 ¥{need:,.0f}" in body
    auto = " · ".join(f"{f.code} ¥{f.daily:,.0f}" for f in cfg.auto_funds)
    assert f"自动定投照常：{auto}。" in body
    assert (
        f"{z1.label}（{z1.range_label}）剩 ¥{z1.budget:,.0f} / ¥{z1.budget:,.0f}，"
        f"按 1.50× 每月动用 ¥{monthly:,.0f}，约可撑 {z1.budget / monthly:.1f} 个月"
    ) in body
    assert f"今日加仓 ¥{need:,.0f} 已自动计入弹药" in body
    assert "本档（1.50×）还可以额外补仓一次" in body
    state, _backend, _error = daily_push.load_state()
    assert state["multiplier"] == 1.5 and state["daily_topup"] == need
    assert state["tier_since"] == "2026-11-16"
    ammo = settings_store.get_ammo()["state"]
    assert ammo["balance"] == cfg.ammo_total - need and ammo["used"]["z1"] == need
    assert any("已记入弹药" in line for line in log)

    status, sent, _ = _run(monday)
    assert status == "duplicate" and not sent

    _run(monday, force=True)  # a forced resend does not book the same day twice
    assert settings_store.get_ammo()["state"]["balance"] == cfg.ammo_total - need


def test_runner_counts_days_and_marks_tier_change(store):
    _run(dt.date(2026, 11, 16))
    _, sent, _ = _run(dt.date(2026, 11, 18))
    assert "距上次换档 2 天，加仓金额不变。" in sent[0][1]

    status, sent, _ = _run(dt.date(2026, 11, 19), vxn=36.0)
    title, body = sent[0]
    old, new = _amount(1.5), _amount(2.0)
    assert title == f"换档 1.5→2.0× · 每日加仓¥{new:,.0f}"
    assert f"**今日手动加仓 ¥{new:,.0f}**（原 ¥{old:,.0f}）" in body
    assert f"今日换档：从今天起每日加仓 ¥{new:,.0f}" in body
    assert f"上次推送：2026-11-18（{fmt_multiplier(1.5)}×）" in body
    assert daily_push.load_state()[0]["tier_since"] == "2026-11-19"


def test_runner_stops_topping_up_when_zone_budget_is_used(store):
    cfg = _cfg()
    z1 = cfg.zones[0].budget
    settings_store.set_ammo(cfg.ammo_total - z1, {"z1": z1})
    _, sent, _ = _run(dt.date(2026, 11, 16))
    title, body = sent[0]
    assert title == "纳指 1.5× · 本区弹药用完 今日不加仓"
    assert "按 1.00× 执行，今日不加仓" in body
    assert settings_store.get_ammo()["state"]["balance"] == cfg.ammo_total - z1


def test_runner_does_not_book_without_recorded_ammo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "LOCAL_PATH", tmp_path / "s.json")
    monkeypatch.setattr(settings_store.database, "get_supabase_client", lambda: None)
    _, sent, _ = _run(dt.date(2026, 11, 16))
    assert "尚未填写" in sent[0][1] and "已自动计入弹药" not in sent[0][1]
    assert settings_store.get_ammo()["state"] == {}


def test_abnormal_day_keeps_last_multiplier(store):
    _run(dt.date(2026, 11, 16))
    sent, log = [], []
    daily_push.run(
        today=dt.date(2026, 11, 17),
        fetch=lambda: ({"value": None}, _vxn(), {}),
        send=lambda t, b: sent.append((t, b)),
        out=log.append,
    )
    assert sent[0][0].startswith("⚠ 数据异常")
    state, _b, _e = daily_push.load_state()
    assert state["multiplier"] == 1.5 and state["sent_date"] == "2026-11-17"


def test_dry_run_sends_and_saves_nothing(store):
    status, sent, log = _run(dt.date(2026, 11, 16), dry_run=True)
    assert status == "dry-run" and not sent
    assert "[dry-run] 标题：纳指 1.5×" in log[0]
    assert daily_push.load_state()[0] == {}
    assert settings_store.get_ammo()["state"]["balance"] == _cfg().ammo_total  # dry run books nothing
