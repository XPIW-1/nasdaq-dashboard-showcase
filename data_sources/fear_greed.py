from datetime import datetime, timezone

import pandas as pd
import requests


CNN_FGI_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"


def fetch_fear_greed():
    """Fetch the US equity Fear & Greed series used beside Nasdaq-100."""
    source = "CNN Fear & Greed (US equities)"
    try:
        response = requests.get(
            CNN_FGI_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Origin": "https://www.cnn.com",
                "Referer": "https://www.cnn.com/markets/fear-and-greed",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        current = payload.get("fear_and_greed") or {}
        history_rows = (payload.get("fear_and_greed_historical") or {}).get("data") or []
        history = []
        dates = []
        for row in history_rows:
            value = float(row["y"])
            stamp = pd.to_datetime(float(row["x"]), unit="ms", utc=True)
            if value == value and not pd.isna(stamp):
                history.append(value)
                dates.append(stamp.date().isoformat())
        value = float(current["score"])
        date = pd.to_datetime(current["timestamp"], utc=True).date().isoformat()
        return {
            "value": value,
            "date": date,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "history": pd.Series(history, index=pd.to_datetime(dates), name="FGI") if history else None,
            "source": source,
            "source_url": CNN_FGI_URL,
            "error": None,
            "note": "美国股票市场情绪参考；仅展示，不参与 Nasdaq-100 建议挡位。",
            "market_scope": "us_equities",
            "eligible_for_multiplier": False,
        }
    except Exception as exc:
        return {
            "value": None,
            "date": None,
            "updated_at": None,
            "history": None,
            "source": source,
            "source_url": CNN_FGI_URL,
            "error": str(exc),
            "note": "股票 FGI 数据不可用；不使用未验证代理值。",
            "market_scope": "us_equities",
            "eligible_for_multiplier": False,
        }
