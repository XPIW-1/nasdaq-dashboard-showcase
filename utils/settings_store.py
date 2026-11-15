"""Small key/value settings (ammo balance, push state).

Supabase first (shared by the page and the phase-3 push job); a git-ignored
local JSON file is the fallback so local runs work without the cloud.
"""
import datetime as dt
import json
import math
from pathlib import Path

from . import database

SETTINGS_TABLE = "nasdaq_dashboard_settings"
LOCAL_PATH = Path(__file__).resolve().parent.parent / "data" / "settings.local.json"
RESERVE_KEY = "reserve_balance"  # pre-2026-11 plan; kept readable only
AMMO_KEY = "ammo_state"
PUSH_STATE_KEY = "push_state"


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _local_read(path=None):
    p = Path(path or LOCAL_PATH)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _local_write(key, value, path=None):
    p = Path(path or LOCAL_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = _local_read(p)
    data[key] = {"value": value, "updated_at": _now()}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data[key]


def get_setting(key):
    """Return ({"value", "updated_at"} | None, backend, error)."""
    client = database.get_supabase_client()
    error = None
    if client is not None:
        try:
            rows = (
                client.table(SETTINGS_TABLE).select("value,updated_at").eq("key", key).limit(1).execute().data
                or []
            )
            return (rows[0] if rows else None), "Supabase", None
        except Exception as exc:  # table missing, network, permissions
            error = str(exc)
    record = _local_read().get(key)
    return record, "Local file", error


def set_setting(key, value):
    """Return (backend, error)."""
    client = database.get_supabase_client()
    error = None
    if client is not None:
        try:
            client.table(SETTINGS_TABLE).upsert(
                {"key": key, "value": value, "updated_at": _now()}, on_conflict="key"
            ).execute()
            return "Supabase", None
        except Exception as exc:
            error = str(exc)
    _local_write(key, value)
    return "Local file", error


def valid_balance(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def get_reserve():
    record, backend, error = get_setting(RESERVE_KEY)
    amount = None
    updated_at = None
    if isinstance(record, dict):
        value = record.get("value")
        if isinstance(value, dict):
            value = value.get("amount")
        amount = valid_balance(value)
        updated_at = record.get("updated_at")
    return {"amount": amount, "updated_at": updated_at, "backend": backend, "error": error}


def set_reserve(amount):
    amount = valid_balance(amount)
    if amount is None:
        raise ValueError("余额必须是大于等于 0 的数字")
    return set_setting(RESERVE_KEY, {"amount": amount})


def days_since(updated_at, now=None):
    if not updated_at:
        return None
    try:
        stamp = dt.datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    now = now or dt.datetime.now(dt.timezone.utc)
    return max((now - stamp).days, 0)


# ---- ammo (2026-11 plan) ----------------------------------------------------

def _clean_ammo(value):
    value = value if isinstance(value, dict) else {}
    used = value.get("used") if isinstance(value.get("used"), dict) else {}
    manual = value.get("manual") if isinstance(value.get("manual"), dict) else {}
    last_auto = value.get("last_auto")
    return {
        "balance": valid_balance(value.get("balance")),
        "used": {str(k): v for k, v in ((k, valid_balance(v)) for k, v in used.items()) if v is not None},
        "manual": {
            str(k): rec
            for k, rec in manual.items()
            if isinstance(rec, dict) and valid_balance(rec.get("amount")) is not None
        },
        "last_auto": last_auto if isinstance(last_auto, dict) else None,
    }


def get_ammo():
    record, backend, error = get_setting(AMMO_KEY)
    value = record.get("value") if isinstance(record, dict) else None
    state = _clean_ammo(value) if isinstance(value, dict) else {}
    return {
        "state": state,
        "updated_at": record.get("updated_at") if isinstance(record, dict) else None,
        "backend": backend,
        "error": error,
    }


def set_ammo(balance, used, manual=None, last_auto=None):
    balance = valid_balance(balance)
    if balance is None:
        raise ValueError("弹药余额必须是大于等于 0 的数字")
    clean_used = {}
    for key, amount in (used or {}).items():
        amount = valid_balance(amount)
        if amount is None:
            raise ValueError("已用额度必须是大于等于 0 的数字")
        clean_used[str(key)] = amount
    state = {"balance": balance, "used": clean_used, "manual": dict(manual or {})}
    if last_auto:
        state["last_auto"] = dict(last_auto)
    return set_setting(AMMO_KEY, state)


def book_topup(state, zone_key, amount, date):
    """Count today's daily top-up against the ammo, once per date.

    Returns (booked, backend, error). Nothing is booked without a recorded
    balance, for a zero amount, or when ``date`` was already booked.
    """
    state = _clean_ammo(state)
    amount = valid_balance(amount)
    if state["balance"] is None or not amount or not zone_key:
        return False, None, None
    if (state["last_auto"] or {}).get("date") == str(date):
        return False, None, None
    used = dict(state["used"])
    used[zone_key] = used.get(zone_key, 0.0) + amount
    backend, error = set_ammo(
        max(state["balance"] - amount, 0.0),
        used,
        state["manual"],
        {"date": str(date), "amount": amount, "zone": zone_key},
    )
    return True, backend, error


def record_manual(state, checkpoint, amount, zone_key, date):
    """Record the one extra manual top-up for ``checkpoint``; it uses ammo."""
    amount = valid_balance(amount)
    if amount is None or amount <= 0:
        raise ValueError("补仓金额必须大于 0")
    state = _clean_ammo(state)
    if checkpoint in state["manual"]:
        raise ValueError(f"{checkpoint} 已经额外补过一次")
    used = dict(state["used"])
    if zone_key:
        used[zone_key] = used.get(zone_key, 0.0) + amount
    balance = max((state["balance"] or 0.0) - amount, 0.0)
    manual = dict(state["manual"])
    manual[checkpoint] = {"amount": amount, "zone": zone_key, "date": str(date)}
    return set_ammo(balance, used, manual, state["last_auto"])


def undo_manual(state, checkpoint):
    state = _clean_ammo(state)
    rec = state["manual"].get(checkpoint)
    if rec is None:
        raise ValueError(f"{checkpoint} 没有额外补仓记录")
    amount = valid_balance(rec.get("amount")) or 0.0
    used = dict(state["used"])
    zone_key = rec.get("zone")
    if zone_key in used:
        used[zone_key] = max(used[zone_key] - amount, 0.0)
    manual = {k: v for k, v in state["manual"].items() if k != checkpoint}
    return set_ammo((state["balance"] or 0.0) + amount, used, manual, state["last_auto"])


def get_push_state():
    record, _backend, _error = get_setting(PUSH_STATE_KEY)
    value = record.get("value") if isinstance(record, dict) else None
    return value if isinstance(value, dict) else {}
