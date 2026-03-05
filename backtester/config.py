"""
Configuration management for the False Breakout Strategy Backtester.

DEFAULT_CONFIG contains all ~60 parameters from L-005.1 §9.
load_config() reads overrides from a JSON/YAML file.
validate_config() ensures all required keys are present.

Reference: L-005.1 spec, Backtester Architecture v1 §7.
"""

import json
import copy
from pathlib import Path
from typing import Any


# ── Default Configuration (L-005.1 §9) ────────────────────────────────────

DEFAULT_CONFIG: dict[str, Any] = {
    # ── Level Detector ──
    "fractal_depth": 10,
    "tolerance_cents": 0.05,
    "tolerance_pct": 0.001,         # 0.1% for stocks > $100
    "price_threshold": 100.0,       # threshold for cents vs pct tolerance
    "atr_period": 5,
    "paranormal_mult": 2.0,         # TR > 2x ATR = paranormal
    "atr_upper_mult": 2.0,          # modified ATR: exclude TR > 2x
    "atr_lower_mult": 0.5,          # modified ATR: exclude TR < 0.5x
    "min_level_score": 5,
    "cross_count_invalidate": 3,    # anti-sawing threshold
    "cross_count_window": 20,       # bars for cross counting

    # ── Mirror Levels ──
    "mirror_atr_distance": 3.0,     # max ATR distance for mirror confirmation
    "mirror_days_beyond": 3,        # min days beyond breakout

    # ── Pattern Engine ──
    "tail_ratio_min": 0.10,
    "lp2_engulfing_required": True,
    "clp_min_bars": 3,
    "clp_max_bars": 7,
    "clp_max_deviation_atr_mult": 2.5,
    "atr_m5_period": 5,

    # ── Filter Chain ──
    "atr_block_threshold": 0.30,    # block if exhaustion < 30%
    "atr_entry_threshold": 0.80,    # ideal entry zone > 80%
    "vol_climax_mult": 2.0,
    "vol_low_mult": 0.7,
    "vol_avg_period": 20,
    "open_delay_minutes": 5,        # skip first 5 min after open
    "market_open_hour_ist": 16,     # 9:30 ET = 16:30 IST
    "market_open_minute": 30,
    "market_close_hour_ist": 23,    # 4:00 PM ET = 23:00 IST
    "earnings_blackout_days": 1,    # days around earnings to skip

    # ── Risk Manager ──
    "min_rr": 3.0,                  # L-005.1 spec minimum R:R
    "max_stop_atr_pct": 0.10,      # max stop as % of ATR_D1
    "stop_buffer_min": 0.02,
    "stop_buffer_atr_mult": 0.10,
    "min_stop_atr_mult": 0.15,
    "min_stop_absolute": 0.05,
    "slippage_per_share": 0.02,     # $0.02 each way
    "risk_pct": 0.003,              # 0.3% of capital per trade
    "capital": 100_000.0,

    # ── Circuit Breakers ──
    "max_consecutive_stops": 3,
    "max_daily_loss_pct": 0.01,     # 1%
    "max_weekly_loss_pct": 0.02,    # 2%
    "max_monthly_loss_pct": 0.08,   # 8%

    # ── Trade Manager ──
    "partial_tp_at_r": 2.0,
    "partial_tp_pct": 0.50,
    "breakeven_stop_dist_mult": 2.0,
    "breakeven_tp_path_pct": 0.50,
    "eod_exit_hour_ist": 22,        # 3:55 PM ET ~ 22:55 IST
    "eod_exit_minute": 55,
    "model4_size_mult": 1.5,

    # ── Tiered Targets (2tier_trail) ──
    "tier_config": {
        "mode": "2tier_trail",
        "t1_pct": 0.30,
        "trail_factor": 0.7,
        "trail_activation_r": 0.0,
        "min_rr": 3.0,
    },

    # ── Intraday Levels ──
    "enable_h1": True,
    "fractal_depth_h1": 3,
    "fractal_depth_m5_intraday": 3,
    "min_target_r": 1.0,
    "level_merge_tolerance": 0.05,
    "intraday_lookback_bars": 500,

    # ── Direction Filter ──
    "direction_filter": {"TSLA": "long", "DEFAULT": "short"},

    # ── Data Split ──
    "in_sample_end": "2025-10-01",
    "out_of_sample_start": "2025-10-01",

    # ── Portfolio ──
    "tickers": [
        "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN", "COST",
        "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU", "NVDA",
        "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
    ],
}

# All keys that must be present for a valid config
REQUIRED_KEYS = set(DEFAULT_CONFIG.keys())


# ── Functions ──────────────────────────────────────────────────────────────

def load_config(path: str | Path) -> dict[str, Any]:
    """Load config from a JSON file, merged over DEFAULT_CONFIG.

    Args:
        path: Path to a JSON config file with parameter overrides.

    Returns:
        Complete config dict (defaults + overrides).

    Raises:
        FileNotFoundError: If path does not exist.
        json.JSONDecodeError: If file is not valid JSON.
    """
    path = Path(path)
    with open(path, "r") as f:
        overrides = json.load(f)

    config = copy.deepcopy(DEFAULT_CONFIG)
    config.update(overrides)
    return config


def validate_config(config: dict[str, Any]) -> list[str]:
    """Validate a config dict has all required keys.

    Args:
        config: Config dict to validate.

    Returns:
        List of error messages. Empty list means valid.

    Raises:
        ValueError: If there are missing required keys.
    """
    errors = []

    # Check for missing required keys
    missing = REQUIRED_KEYS - set(config.keys())
    if missing:
        errors.append(f"Missing required config keys: {sorted(missing)}")

    # Type checks for critical numeric params
    numeric_keys = [
        "fractal_depth", "atr_period", "min_level_score",
        "tail_ratio_min", "atr_block_threshold", "atr_entry_threshold",
        "min_rr", "max_stop_atr_pct", "risk_pct", "capital",
        "slippage_per_share",
    ]
    for key in numeric_keys:
        if key in config and not isinstance(config[key], (int, float)):
            errors.append(f"Config key '{key}' must be numeric, got {type(config[key]).__name__}")

    # Range checks
    if "risk_pct" in config and isinstance(config["risk_pct"], (int, float)):
        if not (0 < config["risk_pct"] <= 0.10):
            errors.append(f"risk_pct must be in (0, 0.10], got {config['risk_pct']}")

    if "min_rr" in config and isinstance(config["min_rr"], (int, float)):
        if config["min_rr"] <= 0:
            errors.append(f"min_rr must be positive, got {config['min_rr']}")

    if "capital" in config and isinstance(config["capital"], (int, float)):
        if config["capital"] <= 0:
            errors.append(f"capital must be positive, got {config['capital']}")

    # tier_config structure
    if "tier_config" in config and config["tier_config"] is not None:
        tc = config["tier_config"]
        if not isinstance(tc, dict):
            errors.append("tier_config must be a dict or None")
        else:
            required_tier_keys = {"mode", "t1_pct", "trail_factor", "trail_activation_r", "min_rr"}
            missing_tier = required_tier_keys - set(tc.keys())
            if missing_tier:
                errors.append(f"tier_config missing keys: {sorted(missing_tier)}")

    if errors:
        raise ValueError("; ".join(errors))

    return errors
