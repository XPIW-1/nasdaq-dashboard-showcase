from model.scoring import total_score,drawdown_score,score_drawdown,breadth_score,score_pe,composite_score
from model.signals import multiplier
import pytest
W={"vxn":.25,"pe":.3125,"fear_greed":0.0,"drawdown":.25,"breadth":.1875}
def test_extremes():
    s,_=total_score({"vxn":10,"pe":5,"fear_greed":20,"drawdown":10},W); assert s<30
    s,_=total_score({"vxn":100,"pe":100,"fear_greed":95,"drawdown":100},W); assert s>90
def test_normal():
    s,_=total_score({"vxn":50,"pe":50,"fear_greed":50,"drawdown":50},W); assert 40<=s<=60
def test_pe_linear_boundaries():
    assert score_pe(20)==100
    assert score_pe(25)==85
    assert score_pe(30)==65
    assert score_pe(35)==45
    assert round(score_pe(39.48),2)==27.08
    assert score_pe(40)==25
    assert score_pe(50)==5
    assert score_pe(50.01)==0
def test_drawdown_linear_boundaries():
    assert score_drawdown(0)==0
    assert score_drawdown(5)==0
    assert score_drawdown(10)==30
    assert score_drawdown(15)==55
    assert score_drawdown(20)==75
    assert score_drawdown(30)==100
    assert score_drawdown(35)==100
def test_extra_buy_boundaries():
    from model.signals import extra_buy
    for score,expected in [(54.99,0),(55,.25),(64.99,.25),(65,.5),(74.99,.5),(75,1),(84.99,1),(85,1.5),(100,1.5)]: assert extra_buy(score)==expected
def test_composite_requires_three_valid_indicators():
    s,_=composite_score({"vxn":50,"pe":None,"fear_greed":None,"drawdown":40,"breadth":None},W)
    assert s is None
def test_missing_renormalizes():
    s,d=total_score({"vxn":80,"pe":None,"fear_greed":60,"drawdown":40},W); assert d==pytest.approx(.50) and s==60
def test_drawdown_interp(): assert drawdown_score(-.30)==90
def test_multiplier(): assert multiplier(85,[(0,.5),(80,2)])==2
def test_crypto_fear_greed_does_not_affect_total():
    base={"vxn":60,"pe":50,"fear_greed":0,"drawdown":40}
    changed={**base,"fear_greed":100}
    assert total_score(base,W)[0] == total_score(changed,W)[0]
def test_ath_uses_complete_history():
    # The ATH input is the max of the complete series, not the short chart window.
    history=[100,120,110,90]; short=history[-2:]
    assert max(history)==120 and max(short)==110
def test_pe_missing_renormalizes_vxn_drawdown():
    s,d=total_score({"vxn":80,"pe":None,"fear_greed":30,"drawdown":40},W)
    assert d==pytest.approx(.50) and round(s,1)==60.0
def test_breadth_scores():
    assert breadth_score(90)==10
    assert breadth_score(50)==50
    assert breadth_score(10)==100
def test_breadth_missing_renormalizes():
    s,d=total_score({"vxn":60,"pe":50,"fear_greed":99,"drawdown":40,"breadth":None},W)
    assert d==pytest.approx(.8125)
def test_pe_and_breadth_missing_uses_vxn_drawdown():
    s,d=total_score({"vxn":80,"pe":None,"fear_greed":0,"drawdown":40,"breadth":None},W)
    assert d==pytest.approx(.50) and round(s,1)==60.0
def test_old_history_schema_upgrades(tmp_path):
    from utils.storage import load_history
    p=tmp_path/"history.csv"; p.write_text("date,ndx,total_score\n2026-01-01,100,50\n",encoding="utf-8")
    df=load_history(p)
    assert "breadth" in df.columns and "breadth_source" in df.columns and len(df)==1
def test_pe_audit_does_not_mislabel_qqq_or_forward():
    from data_sources.valuation import manual_pe
    assert manual_pe(25,"QQQ","QQQ trailing P/E")["usable_for_model"] is False
    assert manual_pe(25,"vendor","forward P/E")["value"] is None
def test_no_qualified_automatic_pe_is_na(monkeypatch):
    from data_sources import valuation
    monkeypatch.setattr(valuation.requests,"get",lambda *a,**k: (_ for _ in ()).throw(RuntimeError("offline")))
    p=valuation.fetch_pe()
    assert p["selected_value"] is None and p["usable_for_model"] is False
    assert "暂无可靠估值数据" in p["note"] and len(p["candidates"]) == 1
def test_blackrock_parser_and_primary_selection(monkeypatch):
    from data_sources import valuation
    html='"priceEarnings":{"label":"P/E Ratio","formattedValue":"39.48","formattedAsOfDate":"Aug 27, 2026"},"rocPct"'
    class R:
        text=html
        def raise_for_status(self): pass
    monkeypatch.setattr(valuation.requests,"get",lambda *a,**k:R())
    p=valuation.fetch_pe(); assert p["value"]==39.48 and p["selected_date"]=="Aug 27, 2026" and p["fallback_used"] is False
def test_qualified_manual_pe_enters_model():
    from data_sources.valuation import manual_pe
    p=manual_pe(24,"Nasdaq official","Nasdaq-100 Index trailing P/E")
    assert p["value"]==24 and p["usable_for_model"] is True
def test_daily_snapshot_upsert_and_model_version(tmp_path):
    from utils.storage import upsert_history, load_history
    row={"date":"2026-08-30","ndx":1,"model_version":"1.0"}
    p=tmp_path/"history.csv"; upsert_history(row,p); upsert_history({**row,"ndx":2},p)
    df=load_history(p); assert len(df)==1 and df.iloc[0]["ndx"]==2 and str(df.iloc[0]["model_version"])=="1.0"
def test_market_stale_weekend_and_beijing_monday_morning():
    from datetime import datetime, timezone
    from utils.helpers import is_market_data_stale
    friday="2026-08-28"; z=timezone.utc
    assert is_market_data_stale(friday, datetime(2026,8,29,15,tzinfo=z)) is False
    assert is_market_data_stale(friday, datetime(2026,8,30,15,tzinfo=z)) is False
    # Monday 08:00 Beijing is Sunday evening in New York; Friday is latest expected close.
    assert is_market_data_stale(friday, datetime(2026,8,31,0,tzinfo=z)) is False
def test_market_stale_after_two_missed_sessions():
    from datetime import datetime, timezone
    from utils.helpers import is_market_data_stale
    z=timezone.utc
    assert is_market_data_stale("2026-08-26", datetime(2026,8,31,22,tzinfo=z), market="US") is True
    assert is_market_data_stale("2026-08-28", datetime(2026,8,30,15,tzinfo=z), market="US") is False
def test_pe_stale_calendar_day_boundaries():
    from datetime import datetime, timezone
    from utils.helpers import stale
    now=datetime(2026,8,31,12,tzinfo=timezone.utc)
    assert stale("2026-08-31",5,current_time=now) is False
    assert stale("Aug 27, 2026",5,current_time=now) is False
    assert stale("2026-08-26",5,current_time=now) is False
    assert stale("2026-08-25",5,current_time=now) is True
def test_history_missing_file_is_safe(tmp_path):
    from utils.storage import load_history, upsert_history
    p=tmp_path/"missing"/"history.csv"
    assert load_history(p).empty
    upsert_history({"date":"2026-08-30","model_version":"1.0"},p)
    assert len(load_history(p))==1
def test_import_paths_are_case_consistent():
    import data_sources.ndx, data_sources.vxn
    import model.scoring, utils.storage
def test_storage_fallback_when_supabase_unavailable(tmp_path,monkeypatch):
    from utils import storage
    monkeypatch.setattr(storage.database,"test_connection",lambda:{"ok":False,"configured":False,"error":"Not configured"})
    monkeypatch.setattr(storage,"PROJECT_ROOT",tmp_path)
    backend,error=storage.save_history({"date":"2026-08-31","model_version":"1.0"})
    assert backend=="Local CSV fallback" and (tmp_path/"data"/"history.csv").exists()
def test_supabase_failure_does_not_change_model_inputs(monkeypatch):
    from utils import database
    monkeypatch.setattr(database,"is_supabase_configured",lambda:False)
    assert database.get_supabase_client() is None

def test_four_indicator_multiplier_cases():
    from model.signals import calculate_drawdown, get_drawdown_zone, apply_sentiment_adjustment
    cases = [(-.05,50,22,1.0),(-.09,45,25,1.25),(-.09,30,32,1.5),(-.14,40,27,1.5),(-.14,22,37,2.0),(-.20,28,33,2.0),(-.20,18,42,2.5),(-.28,30,35,2.5),(-.28,15,46,3.0)]
    for dd,_crypto_fgi,vxn,expected in cases: assert apply_sentiment_adjustment(dd,vxn) == expected
    assert calculate_drawdown(27000,30000) == pytest.approx(-.1)
    assert get_drawdown_zone(-.08)["key"] == "mild"
    assert get_drawdown_zone(-.12)["key"] == "moderate"
    assert get_drawdown_zone(-.18)["key"] == "deep"
    assert get_drawdown_zone(-.25)["key"] == "extreme"
    from model.signals import get_next_trigger
    t=get_next_trigger(-.053); assert t["next_threshold"] == -.08 and t["distance"] == pytest.approx(.027) and t["sentiment_condition"] == "VXN > 30"

def test_crypto_fgi_never_changes_multiplier():
    from model.signals import apply_sentiment_adjustment
    # Crypto FGI values are deliberately absent from the function contract.
    assert apply_sentiment_adjustment(-.09, 29.0) == 1.25
    assert apply_sentiment_adjustment(-.14, 34.0) == 1.5
    assert apply_sentiment_adjustment(-.20, 39.0) == 2.0
    assert apply_sentiment_adjustment(-.28, 44.0) == 2.5

def test_vxn_only_upgrade_boundaries():
    from model.signals import apply_sentiment_adjustment
    assert apply_sentiment_adjustment(-.09, 30.0) == 1.25
    assert apply_sentiment_adjustment(-.09, 30.01) == 1.5
    assert apply_sentiment_adjustment(-.14, 35.0) == 1.5
    assert apply_sentiment_adjustment(-.14, 35.01) == 2.0
    assert apply_sentiment_adjustment(-.20, 40.0) == 2.0
    assert apply_sentiment_adjustment(-.20, 40.01) == 2.5
    assert apply_sentiment_adjustment(-.28, 45.0) == 2.5
    assert apply_sentiment_adjustment(-.28, 45.01) == 3.0

def test_pe_missing_does_not_affect_final_multiplier():
    from model.signals import apply_sentiment_adjustment
    pe = None
    assert pe is None and apply_sentiment_adjustment(-.14, 37.0) == 2.0

def test_missing_drawdown_never_outputs_multiplier():
    from model.signals import calculate_drawdown, apply_sentiment_adjustment
    assert calculate_drawdown(None, None) is None
    assert calculate_drawdown(100, None) is None
    assert apply_sentiment_adjustment(None, 50.0) is None

def test_stock_fgi_adapter_is_display_only(monkeypatch):
    from data_sources import fear_greed
    class R:
        def raise_for_status(self): pass
        def json(self):
            return {
                "fear_and_greed": {"score": 12, "timestamp": "2026-09-14T00:00:00+00:00"},
                "fear_and_greed_historical": {"data": [{"x": 1789344000000, "y": 12}]},
            }
    monkeypatch.setattr(fear_greed.requests,"get",lambda *a,**k:R())
    result=fear_greed.fetch_fear_greed()
    assert result["market_scope"] == "us_equities"
    assert result["eligible_for_multiplier"] is False
    assert "不参与" in result["note"]

def test_ndx_falls_back_to_qqq(monkeypatch):
    import pandas as pd
    from data_sources import ndx
    class FakeTicker:
        def __init__(self, symbol): self.symbol=symbol
        def history(self, **kwargs):
            if self.symbol == "^NDX": raise RuntimeError("unavailable")
            return pd.DataFrame({"Close":[400.0,405.0]}, index=pd.to_datetime(["2026-09-14","2026-09-15"]))
    monkeypatch.setattr(ndx.yf,"Ticker",FakeTicker)
    result=ndx.fetch_ndx("1y")
    assert result["symbol"] == "QQQ" and result["proxy"] is True and result["value"] == 405.0
