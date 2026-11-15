from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf


class InvalidVxnData(ValueError):
    """Raised when fetched VXN history cannot be used safely."""


def clean_price_series(series, *, label="VXN"):
    """Return a sorted, de-duplicated, finite, strictly positive VXN series."""
    if series is None:
        raise InvalidVxnData(f"{label}: no history")
    if isinstance(series, pd.DataFrame):
        if "Close" not in series.columns:
            raise InvalidVxnData(f"{label}: Close column missing")
        series = series["Close"]
    elif not isinstance(series, pd.Series):
        series = pd.Series(series)
    if len(series) == 0:
        raise InvalidVxnData(f"{label}: empty history")

    index = series.index
    if isinstance(index, pd.DatetimeIndex):
        converted = index
    elif pd.api.types.is_object_dtype(index) or pd.api.types.is_string_dtype(index):
        converted = pd.to_datetime(index, errors="coerce")
        if converted.isna().all():
            raise InvalidVxnData(f"{label}: history index is not date-like")
    else:
        raise InvalidVxnData(f"{label}: history index must be a DatetimeIndex")

    values = pd.to_numeric(
        pd.Series(series.to_numpy(), index=converted), errors="coerce"
    ).astype("float64")
    values = values.where(np.isfinite(values))
    mask = values.notna() & (values > 0)
    if not mask.any():
        return pd.Series(dtype=float, name=label)

    cleaned = pd.Series(
        values[mask].to_numpy(dtype=float),
        index=converted[mask.to_numpy()],
        name=label,
    )
    cleaned = cleaned.sort_index()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]
    return cleaned


def _latest_timestamp(index):
    try:
        converted = pd.to_datetime(index, errors="coerce")
    except Exception:
        return None
    if not isinstance(converted, pd.DatetimeIndex):
        return None
    converted = converted[~converted.isna()]
    if len(converted) == 0:
        return None
    return converted.max()


def fetch_vxn(period="10y"):
    """Fetch ^VXN with no upper bound; only finite, positive values are usable.

    A high but finite VXN is a real market observation and must keep flowing
    through the existing sentiment thresholds. Only non-finite, zero, or
    negative observations are rejected.
    """
    try:
        frame = yf.Ticker("^VXN").history(period=period, auto_adjust=False)
        if frame is None or "Close" not in frame:
            raise InvalidVxnData("^VXN: Close column missing")
        close = frame["Close"]
        if close is None or len(close) == 0:
            raise InvalidVxnData("^VXN: empty history")
        cleaned = clean_price_series(close, label="VXN")
        latest = _latest_timestamp(close.index)
        if latest is None or cleaned.empty or cleaned.index[-1] != latest:
            raise InvalidVxnData("^VXN: latest observation is not a finite, positive value")
        return {
            "value": float(cleaned.iloc[-1]),
            "date": cleaned.index[-1].date().isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "history": cleaned,
            "source": "Yahoo Finance (^VXN)",
            "error": None,
            "proxy": False,
            "status": "ok",
            "is_official": True,
        }
    except Exception as e:
        return {
            "value": None,
            "date": None,
            "updated_at": None,
            "history": None,
            "source": "Yahoo Finance (^VXN)",
            "error": str(e),
            "proxy": False,
            "status": "invalid" if isinstance(e, InvalidVxnData) else "unavailable",
            "is_official": False,
        }
