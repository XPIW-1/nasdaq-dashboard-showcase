from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf


class InvalidPriceData(ValueError):
    """Raised when a fetched price history cannot be used safely."""


def clean_price_series(series, *, label="price"):
    """Return a sorted, de-duplicated, finite, strictly positive price series.

    The caller must supply a date-like index; integer positional indexes are
    rejected instead of being silently interpreted as nanosecond timestamps.
    """
    if series is None:
        raise InvalidPriceData(f"{label}: no history")
    if isinstance(series, pd.DataFrame):
        if "Close" not in series.columns:
            raise InvalidPriceData(f"{label}: Close column missing")
        series = series["Close"]
    elif not isinstance(series, pd.Series):
        series = pd.Series(series)
    if len(series) == 0:
        raise InvalidPriceData(f"{label}: empty history")

    index = series.index
    if isinstance(index, pd.DatetimeIndex):
        converted = index
    elif pd.api.types.is_object_dtype(index) or pd.api.types.is_string_dtype(index):
        converted = pd.to_datetime(index, errors="coerce")
        if converted.isna().all():
            raise InvalidPriceData(f"{label}: history index is not date-like")
    else:
        raise InvalidPriceData(f"{label}: history index must be a DatetimeIndex")

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


def rolling_high(history, days=252):
    """Return the high/high-date over the last ``days`` valid observations."""
    if history is None:
        return None
    if not isinstance(history, pd.Series):
        history = pd.Series(history)
    try:
        history = clean_price_series(history, label="history")
    except InvalidPriceData:
        return None
    if history.empty:
        return None
    window = history.tail(days)
    high = float(window.max())
    high_date = window.idxmax()
    high_date = high_date.date().isoformat() if hasattr(high_date, "date") else str(high_date)
    return {
        "high": high,
        "high_date": high_date,
        "window": int(len(window)),
        "window_ok": len(history) >= days,
    }


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


def fetch_ndx(period="10y"):
    errors = []
    invalid = False
    for symbol, source in (("^NDX", "Yahoo Finance (^NDX)"), ("QQQ", "Yahoo Finance QQQ（Nasdaq-100 代理）")):
        try:
            frame = yf.Ticker(symbol).history(period=period, auto_adjust=False)
            if frame is None or "Close" not in frame:
                raise InvalidPriceData(f"{symbol}: Close column missing")
            close = frame["Close"]
            if close is None or len(close) == 0:
                raise InvalidPriceData(f"{symbol}: empty history")
            cleaned = clean_price_series(close, label=symbol)
            latest = _latest_timestamp(close.index)
            if latest is None or cleaned.empty or cleaned.index[-1] != latest:
                raise InvalidPriceData(
                    f"{symbol}: latest observation is not a finite, positive price"
                )
            return {
                "value": float(cleaned.iloc[-1]),
                "date": cleaned.index[-1].date().isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "history": cleaned,
                "symbol": symbol,
                "source": source,
                "error": None,
                "proxy": symbol == "QQQ",
                "is_official": symbol == "^NDX",
                "status": "ok" if symbol == "^NDX" else "proxy",
                "primary_error": None if symbol == "^NDX" else "; ".join(errors),
                "fallback_reason": None if symbol == "^NDX" else (errors[0] if errors else None),
            }
        except Exception as e:
            if isinstance(e, InvalidPriceData):
                invalid = True
            message = str(e)
            errors.append(
                message if message.startswith(f"{symbol}:") else f"{symbol}: {message}"
            )
    return {
        "value": None,
        "date": None,
        "updated_at": None,
        "history": None,
        "symbol": "^NDX",
        "source": "Yahoo Finance (^NDX); QQQ fallback",
        "error": "; ".join(errors),
        "proxy": False,
        "is_official": False,
        "status": "invalid" if invalid else "unavailable",
        "primary_error": "; ".join(errors),
        "fallback_reason": "; ".join(errors),
    }
