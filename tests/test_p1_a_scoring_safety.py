from pathlib import Path

import pandas as pd
import pytest
from streamlit import cache_data
from streamlit.testing.v1 import AppTest

import data_sources.fear_greed as fgi_mod
import data_sources.ndx as ndx_mod
import data_sources.valuation as pe_mod
import data_sources.vxn as vxn_mod
import model.scoring as scoring_mod
import utils.storage as storage_mod
from config import DASHBOARD_MIN_VALID, DASHBOARD_WEIGHTS, DEFAULT_WEIGHTS
from model.scoring import (
    composite_score,
    confidence,
    fallback_vxn,
    percentile_score,
    score_drawdown,
    score_pe,
    total_score,
)
from utils import helpers

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
TODAY = pd.Timestamp.today().date().isoformat()
HISTORY = list(range(1, 101))
NON_FINITE = [None, float("nan"), float("inf"), float("-inf")]


def test_dashboard_weight_config_is_explicit_and_unchanged():
    assert DASHBOARD_WEIGHTS == {"vxn": .375, "pe": .3125, "drawdown": .3125}
    assert sum(DASHBOARD_WEIGHTS.values()) == pytest.approx(1.0)
    assert DASHBOARD_MIN_VALID == 2
    # The historical five-indicator baseline is a different configuration.
    assert DEFAULT_WEIGHTS != DASHBOARD_WEIGHTS
    assert "breadth" not in DASHBOARD_WEIGHTS


@pytest.mark.parametrize("value", NON_FINITE)
def test_score_pe_rejects_missing_and_non_finite(value):
    assert score_pe(value) is None


@pytest.mark.parametrize("value", [0, 0.0, -1, -5])
def test_score_pe_rejects_non_positive_pe(value):
    assert score_pe(value) is None


@pytest.mark.parametrize("value", NON_FINITE)
def test_score_drawdown_rejects_missing_and_non_finite(value):
    assert score_drawdown(value) is None


@pytest.mark.parametrize("value", [100.01, -100.01])
def test_score_drawdown_rejects_impossible_magnitude(value):
    assert score_drawdown(value) is None


@pytest.mark.parametrize("value", NON_FINITE)
def test_percentile_score_rejects_missing_and_non_finite(value):
    assert percentile_score(value, HISTORY) is None


def test_percentile_score_ignores_invalid_history_points():
    messy = [float("nan"), float("inf"), float("-inf")] + HISTORY
    assert percentile_score(50.0, messy) == 50.0
    assert percentile_score(50.0, ["not-a-number"] * 25) is None


@pytest.mark.parametrize("value", NON_FINITE + [0, -1, -5])
def test_fallback_vxn_rejects_invalid_input(value):
    assert fallback_vxn(value) is None


def test_scoring_functions_reject_non_numeric_strings():
    assert score_pe("n/a") is None
    assert score_drawdown("n/a") is None
    assert percentile_score("n/a", HISTORY) is None
    assert fallback_vxn("n/a") is None


def test_scoring_functions_reject_overflowing_numbers():
    assert score_pe(10 ** 400) is None
    assert score_drawdown(10 ** 400) is None
    assert percentile_score(50.0, [10 ** 400] * 25) is None
    assert fallback_vxn(10 ** 400) is None


def test_legal_zero_scores_are_not_missing_values():
    assert percentile_score(0.0, HISTORY) == 0.0
    assert percentile_score(100.0, HISTORY, inverse=True) == 0.0
    assert score_drawdown(0.0) == 0.0
    assert score_pe(50.01) == 0.0

    scores = {"vxn": 0.0, "pe": 0.0, "drawdown": 0.0}
    score, weight = composite_score(scores, DASHBOARD_WEIGHTS, min_valid=2)
    assert score == 0.0
    assert weight == pytest.approx(1.0)
    assert confidence(scores, DASHBOARD_WEIGHTS) == 100.0


def test_composite_gates_on_finite_valid_score_count():
    none_valid = {"vxn": None, "pe": float("nan"), "drawdown": float("inf")}
    assert composite_score(none_valid, DASHBOARD_WEIGHTS, min_valid=2) == (None, 0.0)

    one_valid = {"vxn": 80, "pe": None, "drawdown": float("nan")}
    assert composite_score(one_valid, DASHBOARD_WEIGHTS, min_valid=2) == (None, 0.0)

    two_valid = {"vxn": 80, "pe": None, "drawdown": 30}
    score, weight = composite_score(two_valid, DASHBOARD_WEIGHTS, min_valid=2)
    assert score == pytest.approx(57.3)
    assert weight == pytest.approx(.6875)

    three_valid = {"vxn": 80, "pe": 65, "drawdown": 30}
    score, weight = composite_score(three_valid, DASHBOARD_WEIGHTS, min_valid=2)
    assert score == pytest.approx(59.7)
    assert weight == pytest.approx(1.0)


def test_composite_default_min_valid_is_still_three():
    scores = {"vxn": 80, "drawdown": 30}
    assert composite_score(scores, DASHBOARD_WEIGHTS) == (None, 0.0)
    assert composite_score(scores, DASHBOARD_WEIGHTS, min_valid=2)[0] == pytest.approx(57.3)


def test_missing_score_renormalizes_dashboard_weights():
    score, weight = total_score({"vxn": 80, "pe": None, "drawdown": 30}, DASHBOARD_WEIGHTS)
    assert weight == pytest.approx(.6875)
    assert score == pytest.approx(57.3)

    zero_score, zero_weight = total_score(
        {"vxn": 0.0, "pe": None, "drawdown": 30}, DASHBOARD_WEIGHTS
    )
    assert zero_weight == pytest.approx(.6875)
    assert zero_score == pytest.approx(13.6)


def test_total_score_ignores_unknown_and_zero_weight_keys():
    score, weight = total_score(
        {"vxn": 80, "unknown": 100, "drawdown": 30}, DASHBOARD_WEIGHTS
    )
    assert weight == pytest.approx(.6875)
    assert score == pytest.approx(57.3)
    assert total_score({"vxn": 80}, {"vxn": 0.0}) == (None, 0.0)


def test_confidence_counts_only_finite_valid_scores():
    assert confidence({"vxn": 50, "pe": 30, "drawdown": 20}, DASHBOARD_WEIGHTS) == 100.0
    assert confidence({"vxn": 50, "pe": None, "drawdown": 20}, DASHBOARD_WEIGHTS) == 68.8
    assert confidence(
        {"vxn": 50, "pe": float("nan"), "drawdown": float("inf")}, DASHBOARD_WEIGHTS
    ) == 37.5
    assert confidence(
        {"vxn": None, "pe": float("nan"), "drawdown": float("-inf")}, DASHBOARD_WEIGHTS
    ) == 0.0
    assert confidence({"vxn": 0.0, "pe": 0.0, "drawdown": 0.0}, DASHBOARD_WEIGHTS) == 100.0


def test_confidence_stale_penalty_only_applies_to_finite_scores():
    assert confidence(
        {"vxn": 50, "pe": 30, "drawdown": 20}, DASHBOARD_WEIGHTS, {"pe": True}
    ) == 92.2
    assert confidence(
        {"vxn": 50, "pe": float("nan"), "drawdown": 20},
        DASHBOARD_WEIGHTS,
        {"pe": True},
    ) == 68.8


def test_normal_finite_pe_and_drawdown_results_unchanged():
    assert score_pe(20) == 100.0
    assert score_pe(25) == 85.0
    assert score_pe(30) == 65.0
    assert score_pe(35) == 45.0
    assert score_pe(39.48) == pytest.approx(27.08)
    assert score_pe(40) == 25.0
    assert score_pe(50) == 5.0
    assert score_pe(50.01) == 0.0

    assert score_drawdown(0) == 0.0
    assert score_drawdown(5) == 0.0
    assert score_drawdown(10) == 30.0
    assert score_drawdown(15) == 55.0
    assert score_drawdown(20) == 75.0
    assert score_drawdown(25) == pytest.approx(82.5)
    assert score_drawdown(30) == 100.0
    assert score_drawdown(35) == 100.0
    assert score_drawdown(100) == 100.0
    assert score_drawdown(-20) == 75.0


def test_normal_finite_percentile_fallback_and_total_results_unchanged():
    assert percentile_score(0.0, HISTORY) == 0.0
    assert percentile_score(1.0, HISTORY) == 1.0
    assert percentile_score(50.0, HISTORY) == 50.0
    assert percentile_score(100.0, HISTORY) == 100.0
    assert percentile_score(50.0, HISTORY, inverse=True) == 50.0
    assert percentile_score(100.0, HISTORY, inverse=True) == 0.0

    assert fallback_vxn(14.9) == 10
    assert fallback_vxn(15) == 30
    assert fallback_vxn(20) == 50
    assert fallback_vxn(25) == 65
    assert fallback_vxn(30) == 80
    assert fallback_vxn(35) == 90
    assert fallback_vxn(45) == 100
    assert fallback_vxn(100) == 100

    assert total_score(
        {"vxn": 80, "pe": None, "fear_greed": 60, "drawdown": 40}, DEFAULT_WEIGHTS
    ) == (60.0, pytest.approx(.5))


def _series(values=None, periods=260):
    index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=periods)
    if values is None:
        values = [100.0 + i * 0.1 for i in range(periods)]
    return pd.Series(values, index=index, dtype=float)


def _flat_history(high=120.0, current=100.0, periods=260):
    values = [high] * periods
    values[-1] = current
    return _series(values, periods=periods)


def _ndx_result(series):
    ordered = series.sort_index()
    return {
        "value": float(ordered.iloc[-1]),
        "date": ordered.index[-1].date().isoformat(),
        "updated_at": "2026-01-01T00:00:00Z",
        "history": series,
        "symbol": "^NDX",
        "source": "test NDX",
        "error": None,
        "proxy": False,
        "status": "ok",
    }


def _vxn_result(value=22.0):
    series = _series([float(value)] * 260)
    return {
        "value": value,
        "date": series.index[-1].date().isoformat(),
        "updated_at": "2026-01-01T00:00:00Z",
        "history": series,
        "source": "test VXN",
        "error": None,
        "proxy": False,
        "status": "ok",
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
        "usable_for_model": True,
    }


def _run_app(monkeypatch, pe_value=30.0):
    monkeypatch.setattr(helpers, "is_market_data_stale", lambda *args, **kwargs: False)
    monkeypatch.setattr(ndx_mod, "fetch_ndx", lambda period="2y": _ndx_result(_flat_history()))
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
    monkeypatch.setattr(pe_mod, "fetch_pe", lambda: _pe_result(pe_value))
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


def test_app_saves_indicator_scores_without_a_composite(monkeypatch):
    app, saved = _run_app(monkeypatch)
    assert not app.exception
    # The composite score was removed from the dashboard (display and history).
    assert not any(item.label == "综合评分" for item in app.metric)
    assert _metric(app, "最终建议倍数") == "1.50×"

    assert len(saved) == 1
    row = saved[0]
    assert row["vxn_score"] == pytest.approx(100.0)
    assert row["pe_score"] == pytest.approx(65.0)
    assert row["drawdown_score"] == pytest.approx(61.7)
    assert row["total_score"] is None
    assert row["confidence"] is None
    assert row["multiplier"] == pytest.approx(1.5)


def test_legal_zero_vxn_score_does_not_trigger_fallback(monkeypatch):
    monkeypatch.setattr(
        scoring_mod,
        "percentile_score",
        lambda value, history, inverse=False: 0.0,
    )

    def unexpected_fallback(value):
        raise AssertionError("fallback_vxn must not run for a legal 0.0 score")

    monkeypatch.setattr(scoring_mod, "fallback_vxn", unexpected_fallback)

    app, saved = _run_app(monkeypatch)
    assert not app.exception
    assert _metric(app, "评分") == "0.0"
    assert saved[0]["vxn_score"] == 0.0
    assert _metric(app, "最终建议倍数") == "1.50×"


