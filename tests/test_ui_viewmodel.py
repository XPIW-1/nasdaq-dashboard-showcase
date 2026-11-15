import pandas as pd
import pytest

from config import DRAWDOWN_ZONES
from model.signals import apply_sentiment_adjustment, get_drawdown_zone
from ui import render, viewmodel as vm


def test_vxn_upgrade_table_matches_the_model():
    for zone in DRAWDOWN_ZONES:
        dd = max(zone["min_dd"], -0.30) + 0.001 if zone["key"] != "normal" else -0.01
        assert get_drawdown_zone(dd)["key"] == zone["key"]
        if zone["key"] == "normal":
            assert apply_sentiment_adjustment(dd, 99) == 1.0
            continue
        threshold, upgraded = vm.VXN_UPGRADES[zone["key"]]
        assert apply_sentiment_adjustment(dd, threshold) == zone["base"]
        assert apply_sentiment_adjustment(dd, threshold + 0.01) == upgraded


def test_reason_and_next_steps_for_final_reading():
    zone = get_drawdown_zone(-0.142)
    reason = vm.build_reason("final", -0.142, zone, 31.0, True)
    assert "回撤 -14.2%" in reason and "-12%～-18%" in reason
    assert "未达 35" in reason and "不上调" in reason
    lines = vm.build_next_steps("final", -0.142, zone, 31.0, True)
    assert lines[0] == "VXN 再升 4.0 点（超过 35）→ 上调到 2.00×"
    # -14.2% -> -18% needs the index to fall (0.82 / 0.858 - 1) = 4.4%
    assert "指数再跌 4.4%（回撤到 -18%）→ 进入 2.00× 档" == lines[1]


def test_unavailable_reading_has_no_numbers():
    assert "不生成倍数" in vm.build_reason("unavailable", None, None, None, False)
    assert vm.build_next_steps("unavailable", None, None, None, False) == []


def test_base_only_reason_mentions_vxn_unavailable():
    zone = get_drawdown_zone(-0.10)
    assert "VXN 不可用" in vm.build_reason("base_only", -0.10, zone, None, False)


def test_pe_hint_thresholds():
    assert vm.build_pe_hint(35.0, True)["level"] == "warn"
    assert vm.build_pe_hint(22.0, True)["level"] == "ok"
    assert vm.build_pe_hint(30.0, True) is None
    assert vm.build_pe_hint(40.0, False) is None


def test_previous_multiplier_and_tier_change():
    history = pd.DataFrame(
        [
            {"date": "2026-11-10", "multiplier": 1.25},
            {"date": "2026-11-12", "multiplier": 1.5},
            {"date": "2026-11-13", "multiplier": None},
            {"date": "2026-11-14", "multiplier": 2.0},
        ]
    )
    assert vm.previous_multiplier(history, "2026-11-14") == 1.5
    assert vm.tier_change(2.0, 1.5) == "up"
    assert vm.tier_change(1.25, 1.5) == "down"
    assert vm.tier_change(1.5, 1.5) is None
    assert vm.tier_change(1.5, None) is None


def test_ladder_position_is_piecewise_and_clamped():
    assert vm.ladder_position(0.0) == 0.0
    assert vm.ladder_position(-0.175) == pytest.approx(vm.LADDER_SPLIT / 2)
    assert vm.ladder_position(-0.35) == pytest.approx(vm.LADDER_SPLIT)
    assert vm.ladder_position(-0.45) == pytest.approx(vm.LADDER_SPLIT + (1 - vm.LADDER_SPLIT) / 2)
    assert vm.ladder_position(-0.55) == pytest.approx(1.0)
    assert vm.ladder_position(-0.70) == 1.0
    assert vm.ladder_position(None) is None


def test_deep_zone_next_steps_point_at_checkpoints():
    zone = get_drawdown_zone(-0.30)
    lines = vm.build_next_steps("final", -0.30, zone, 50.0, True)
    assert lines[-1].endswith("→ 进入弹药保留区，倍数仍为最高档")
    zone = get_drawdown_zone(-0.40)
    assert vm.build_next_steps("final", -0.40, zone, 50.0, True)[-1].endswith("（回撤到 -45%）→ 新档位，可手动补仓一次")
    assert vm.build_next_steps("final", -0.60, zone, 50.0, True)[-1] == "已越过 -55%，倍数维持最高档。"


def test_tier_since():
    records = [("2026-11-10", 1.25), ("2026-11-11", 1.5), ("2026-11-12", None), ("2026-11-13", 1.5)]
    info = vm.tier_since(records, 1.5, "2026-11-16")
    assert info == {"since": pd.Timestamp("2026-11-11").date(), "days": 5, "previous": 1.25, "changed_today": False}
    changed = vm.tier_since(records, 2.0, "2026-11-16")
    assert changed["changed_today"] and changed["previous"] == 1.5 and changed["days"] == 0
    assert vm.tier_since([], 1.5, "2026-11-16") is None
    # records from today are ignored (the page may already have saved today's row)
    assert vm.tier_since([("2026-11-16", 2.0), ("2026-11-13", 1.5)], 1.5, "2026-11-16")["changed_today"] is False


def test_render_escapes_text_and_marks_current_segment():
    html = render.readout(
        value=1.5,
        kind_label="<b>",
        reason="a<script>",
        next_lines=[],
        fresh={"level": "ok", "text": "ok"},
        issues=[],
        pe_hint=None,
        change="up",
        animate=False,
    )
    assert "&lt;script&gt;" in html and "今日升档" in html
    ladder = render.ladder(
        dd=-0.14, position=0.4, zone_key="moderate", decidable=True,
        vxn_value=31.0, vxn_live=True, flash=False, animate=False,
    )
    assert ladder.count('class="seg current"') == 1
    assert "-14.0%" in ladder
