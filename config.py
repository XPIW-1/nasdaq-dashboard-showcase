from dataclasses import dataclass, field
MODEL_VERSION = "2.0.0"
# Historical five-indicator model baseline. The dashboard does NOT use this
# dict: it scores only VXN/PE/drawdown and must use DASHBOARD_WEIGHTS below.
DEFAULT_WEIGHTS = {"vxn": .25, "pe": .3125, "fear_greed": 0.0, "drawdown": .25, "breadth": .1875}
# Effective composite-score configuration for the dashboard. Keep this as the
# single source for app.py; it is intentionally different from DEFAULT_WEIGHTS
# because fear_greed (display only) and breadth are not part of the composite.
DASHBOARD_WEIGHTS = {"vxn": .375, "pe": .3125, "drawdown": .3125}
DASHBOARD_MIN_VALID = 2
EXTRA_BUY_BANDS = [(0,0.0),(55,0.25),(65,0.50),(75,1.0),(85,1.50)]
DEFAULT_MULTIPLIERS = [(0,.5),(30,.75),(45,1.0),(60,1.25),(70,1.5),(80,2.0),(90,2.5),(101,2.5)]

# Drawdown bands are expressed as negative fractions and are intentionally
# defined with a single, ordered set of boundaries so no value is ambiguous.
DRAWDOWN_ZONES = [
    {"key": "normal", "min_dd": -0.08, "max_dd": 0.0, "label": "正常波动", "base": 1.0},
    {"key": "mild", "min_dd": -0.12, "max_dd": -0.08, "label": "轻度回调", "base": 1.25},
    {"key": "moderate", "min_dd": -0.18, "max_dd": -0.12, "label": "中度回调", "base": 1.5},
    {"key": "deep", "min_dd": -0.25, "max_dd": -0.18, "label": "深度回撤", "base": 2.0},
    {"key": "extreme", "min_dd": float("-inf"), "max_dd": -0.25, "label": "极端回撤", "base": 2.5},
]
@dataclass
class ModelConfig:
    weights: dict = field(default_factory=lambda: DEFAULT_WEIGHTS.copy())
    percentile_years: int = 10
    multipliers: list = field(default_factory=lambda: DEFAULT_MULTIPLIERS.copy())

# PE valuation hints (display only; never change the multiplier).
PE_HIGH = 35.0
PE_LOW = 22.0

# Deep drawdown checkpoints below the deepest multiplier zone. The multiplier
# stays capped at 3.00x; each checkpoint is a new tier for the "one manual
# top-up per tier" rule, and the ladder marks them (with the -35% ammo line).
AMMO_RESERVE_DD = -0.35
DEEP_CHECKPOINTS = (-0.45, -0.55)
