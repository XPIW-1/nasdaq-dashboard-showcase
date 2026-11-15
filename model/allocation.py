"""Fixed auto-invest, the daily manual top-up and the ammo tracker.

Rules (2026-11-15 plan, daily top-up version):
- auto-invest is fixed: each fund's ``daily`` amount, whatever the multiplier;
  their sum is the 1.00x base;
- daily manual top-up = base x (multiplier - 1), rounded half-up to whole
  yuan, filled into funds with a ``topup_priority`` in that order, each up
  to its daily cap minus its auto-invest amount; what does not fit is
  reported as over cap;
- only the top-up uses ammo: monthly draw = base x (multiplier - 1) x 21;
- ammo is split into drawdown zones; once a zone's budget is used up the
  top-up stops (1.00x) until the drawdown reaches the next zone.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
import math

import yaml

from config import DEEP_CHECKPOINTS

FUNDS_PATH = Path(__file__).resolve().parent.parent / "funds.yaml"
TIERS = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0)


@dataclass(frozen=True)
class Fund:
    name: str
    code: str | None
    platform: str
    daily: float
    cap: float | None
    paused: bool = False
    topup_priority: int | None = None
    manual_only: bool = False

    @property
    def auto(self):
        return not self.paused and self.daily > 0

    @property
    def room(self):
        """Top-up room per day; None means no cap."""
        if self.paused or self.topup_priority is None:
            return 0.0
        if self.cap is None:
            return None
        return max(float(self.cap) - float(self.daily), 0.0)

    @property
    def label(self):
        return f"{self.name}（{self.code}）" if self.code else self.name


@dataclass(frozen=True)
class AmmoZone:
    key: str
    label: str
    from_dd: float
    to_dd: float | None
    budget: float

    def contains(self, dd):
        # Same boundary convention as model.signals.get_drawdown_zone:
        # a value exactly on a boundary belongs to the deeper zone.
        return dd <= self.from_dd + 1e-12 and (self.to_dd is None or dd > self.to_dd + 1e-12)

    @property
    def range_label(self):
        start = f"{self.from_dd * 100:.0f}%"
        return f"{start}～{self.to_dd * 100:.0f}%" if self.to_dd is not None else f"≤ {start}"


@dataclass
class Config:
    funds: list
    trading_days: int = 21
    ammo_name: str = "加仓弹药"
    ammo_total: float = 0.0
    ammo_buffer: float = 0.0
    zones: list = field(default_factory=list)

    @property
    def base(self):
        return sum(f.daily for f in self.funds if f.auto)

    @property
    def auto_funds(self):
        return [f for f in self.funds if f.auto]


@dataclass
class TopUp:
    multiplier: float
    base: float
    needed: int = 0
    items: list = field(default_factory=list)  # [(Fund, amount)]
    over_cap: int = 0
    limited_to: int | None = None  # capped by the ammo zone's remaining budget

    @property
    def total(self):
        return sum(amount for _fund, amount in self.items)


def _num(value, default=None):
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def round_yuan(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def load_config(path=None):
    """Return a Config. Raises ValueError on a malformed file."""
    raw = yaml.safe_load(Path(path or FUNDS_PATH).read_text(encoding="utf-8")) or {}
    plan = raw.get("plan") or {}

    funds = []
    for entry in raw.get("funds") or []:
        if not entry.get("name"):
            raise ValueError("funds.yaml: every fund needs a name")
        daily = _num(entry.get("daily"), 0.0)
        cap = _num(entry.get("cap"))
        if daily < 0 or (cap is not None and cap < 0):
            raise ValueError(f"funds.yaml: negative value for {entry['name']}")
        code = entry.get("code")
        priority = entry.get("topup_priority")
        funds.append(
            Fund(
                name=str(entry["name"]),
                code=None if code in (None, "") else str(code),
                platform=str(entry.get("platform") or ""),
                daily=daily,
                cap=cap,
                paused=bool(entry.get("paused", False)),
                topup_priority=None if priority is None else int(priority),
                manual_only=bool(entry.get("manual_only", False)),
            )
        )
    config = Config(funds=funds, trading_days=int(plan.get("trading_days_per_month", 21)))
    if config.base <= 0:
        raise ValueError("funds.yaml: no fund with a positive daily auto-invest amount")

    ammo = raw.get("ammo") or {}
    for entry in ammo.get("zones") or []:
        budget = _num(entry.get("budget"))
        start = _num(entry.get("from_dd"))
        if budget is None or budget < 0 or start is None:
            raise ValueError("funds.yaml: every ammo zone needs from_dd and a budget")
        config.zones.append(
            AmmoZone(
                key=str(entry.get("key") or entry.get("label")),
                label=str(entry.get("label") or entry.get("key")),
                from_dd=start,
                to_dd=_num(entry.get("to_dd")),
                budget=budget,
            )
        )
    config.ammo_name = str(ammo.get("name") or "加仓弹药")
    config.ammo_total = _num(ammo.get("total"), sum(z.budget for z in config.zones))
    config.ammo_buffer = _num(ammo.get("buffer"), 0.0)
    return config


def daily_topup(multiplier, config, limit=None):
    """Today's manual top-up; ``limit`` caps it (the ammo zone's remaining)."""
    m = _num(multiplier)
    result = TopUp(multiplier=m if m is not None else 1.0, base=config.base)
    if m is None or m <= 1.0:
        return result
    needed = round_yuan(config.base * (m - 1.0))
    result.needed = needed
    target = needed
    limit = _num(limit)
    if limit is not None and limit < needed:
        target = max(int(limit), 0)
        result.limited_to = target
    remaining = target
    eligible = sorted(
        (f for f in config.funds if f.topup_priority is not None and not f.paused),
        key=lambda f: f.topup_priority,
    )
    for fund in eligible:
        if remaining <= 0:
            break
        room = fund.room
        take = remaining if room is None else min(int(room), remaining)
        if take > 0:
            result.items.append((fund, take))
            remaining -= take
    result.over_cap = remaining
    return result


def tier_table(config):
    return [daily_topup(tier, config) for tier in TIERS]


def monthly_draw(multiplier, config):
    """Ammo used per month by the top-up at ``multiplier`` (0 at 1.00x)."""
    m = _num(multiplier, 1.0)
    return max(config.base * (m - 1.0) * config.trading_days, 0.0)


def ammo_zone(dd, config):
    dd = _num(dd)
    if dd is None:
        return None
    return next((zone for zone in config.zones if zone.contains(dd)), None)


def checkpoint(dd, multiplier):
    """Label of the tier an extra manual top-up belongs to (one per tier), or None."""
    dd = _num(dd)
    m = _num(multiplier)
    if dd is not None:
        for level in sorted(DEEP_CHECKPOINTS):  # deepest first
            if dd <= level + 1e-12:
                return f"{level * 100:.0f}%"
    if m is not None and m > 1.0:
        return f"{m:.2f}×"
    return None


def ammo_status(dd, multiplier, config, state):
    """Describe today's ammo position.

    ``state`` is the saved {"balance", "used": {zone_key: amount}} (or empty).
    ``effective`` is the multiplier to top up at: 1.00x once the current
    zone's budget is used up.
    """
    m = _num(multiplier)
    state = state if isinstance(state, dict) else {}
    used_map = state.get("used") if isinstance(state.get("used"), dict) else {}
    balance = _num(state.get("balance"))
    zone = ammo_zone(dd, config)
    result = {
        "zone": zone,
        "balance": balance,
        "recorded": bool(state) and balance is not None,
        "used": None,
        "remaining": None,
        "exhausted": False,
        "multiplier": m,
        "effective": m,
        "monthly": 0.0,
        "months_left": None,
        "short_of_balance": False,
    }
    if m is None:
        return result
    if zone is not None:
        used = max(_num(used_map.get(zone.key), 0.0), 0.0)
        remaining = max(zone.budget - used, 0.0)
        result.update(used=used, remaining=remaining)
        if m > 1.0 and remaining <= 0:
            result.update(exhausted=True, effective=1.0)
    monthly = monthly_draw(result["effective"], config)
    result["monthly"] = monthly
    if monthly > 0 and result["remaining"] is not None:
        available = result["remaining"]
        if balance is not None and balance < available:
            available = balance
            result["short_of_balance"] = True
        result["months_left"] = available / monthly
    return result


def topup_for(ammo, config):
    """Today's top-up given an ammo status (capped by the zone's remaining)."""
    return daily_topup(ammo["effective"], config, limit=ammo.get("remaining"))
