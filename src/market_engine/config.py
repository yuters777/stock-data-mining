"""
Market engine configuration.

Feature flags and budget parameters for the XVAL cross-validation layer.
All XVAL features default to DISABLED.
"""

import os


def _env_bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default)).lower() in ("true", "1", "yes")


def _env_float(key: str, default: float) -> float:
    return float(os.environ.get(key, str(default)))


def _env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, str(default)))


# ── XVAL Guard (CC-XVAL-2) ──────────────────────────────────────────────────
NEWS_XVAL_GUARD_ENABLED: bool = _env_bool("NEWS_XVAL_GUARD_ENABLED", False)

# ── XVAL Audit (CC-XVAL-3) ──────────────────────────────────────────────────
NEWS_XVAL_AUDIT_ENABLED: bool = _env_bool("NEWS_XVAL_AUDIT_ENABLED", False)
NEWS_XVAL_AUDIT_DAILY_DISC_CAP: int = _env_int("NEWS_XVAL_AUDIT_DAILY_DISC_CAP", 10)

# ── XVAL Near-Miss (CC-XVAL-3) ──────────────────────────────────────────────
NEWS_XVAL_NEARMISS_ENABLED: bool = _env_bool("NEWS_XVAL_NEARMISS_ENABLED", False)
NEWS_XVAL_NEARMISS_DAILY_CAP: int = _env_int("NEWS_XVAL_NEARMISS_DAILY_CAP", 5)
NEWS_XVAL_NEARMISS_WEEKLY_CAP: int = _env_int("NEWS_XVAL_NEARMISS_WEEKLY_CAP", 25)

# ── XVAL Budget (CC-XVAL-3) ─────────────────────────────────────────────────
NEWS_XVAL_WEEKLY_COST_CEILING: float = _env_float("NEWS_XVAL_WEEKLY_COST_CEILING", 1.50)
NEWS_XVAL_GUARD_RESERVED_BUDGET: float = _env_float("NEWS_XVAL_GUARD_RESERVED_BUDGET", 0.50)

# ── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")
