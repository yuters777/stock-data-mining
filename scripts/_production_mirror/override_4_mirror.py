"""Override 4.0 state derivation for backtest (production-mirror, 95% fidelity).

Production reference: market-engine Override 4.0 spec
(Temporal_Market_Structure_Framework_v7_1.html):
  NORMAL:    VIX < 20                             → 1.00× sizing
  ELEVATED:  VIX 20-25                            → 0.95× sizing (PI v48 frozen)
  HIGH_RISK: VIX ≥ 25 OR (VIX 20-25 AND gap > 1%) → 0.50× sizing
  SUSPENDED: GeoStress ≥3 components              → 0× sizing  [EXCLUDED]
  STALE:     VIX freshness > 60s                  → 0× sizing  [EXCLUDED — N/A in backtest]

HARN-D-5: SUSPENDED/STALE never returned in v1.0. GeoStress excluded per
operator-approved 95% fidelity decision (Day 43). Modules check for
SUSPENDED/STALE but never block on these states.

HARN-1.1: HARN-D-8 closed. VIX now loaded via _data_paths.load_vix() which
reads VIX_daily.csv (canonical FRED VIXCLS, 30-day) and hard-rejects VXVCLS.csv.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from scripts._production_mirror._data_paths import load_vix

VIX_NORMAL_MAX = 20.0
VIX_HIGH_RISK_MIN = 25.0
GAP_HIGH_RISK_THRESHOLD_PCT = 1.0


def load_vix_daily() -> pd.DataFrame:
    """Load canonical VIX daily data via _data_paths canonical loader.

    HARN-1.1: Delegates to _data_paths.load_vix() which reads VIX_daily.csv
    (FRED VIXCLS, 30-day) and hard-rejects VXVCLS.csv (VIX3M).
    Fixes HARN-D-8 silent semantic drift that caused M4 N=4 vs canonical 47.
    """
    return load_vix()


def derive_override_state(
    vix_prior_close: Optional[float],
    gap_pct: Optional[float] = None,
) -> str:
    """Derive Override state for one trading day.

    Args:
        vix_prior_close: VIX close from previous trading day
            (production uses prior, not today).
        gap_pct: Today's open-vs-prior-close gap in percent (signed). Optional.

    Returns: 'NORMAL' | 'ELEVATED' | 'HIGH_RISK'

    Note: SUSPENDED/STALE NOT derivable in standalone backtest (95% fidelity).
    """
    if vix_prior_close is None:
        # Production blocks; backtest treats as ELEVATED (conservative)
        return "ELEVATED"

    if vix_prior_close >= VIX_HIGH_RISK_MIN:
        return "HIGH_RISK"

    if vix_prior_close >= VIX_NORMAL_MAX:
        if gap_pct is not None and abs(gap_pct) > GAP_HIGH_RISK_THRESHOLD_PCT:
            return "HIGH_RISK"
        return "ELEVATED"

    return "NORMAL"


def build_override_history(vix_daily_df: pd.DataFrame) -> pd.DataFrame:
    """Build per-day Override state history from VIX daily.

    vix_daily_df: columns ['date' (datetime), 'vix_close' (float)] — sorted.
    Returns DataFrame with columns: date_et (date), vix_prior_close (float),
    override_state (str).

    Note: gap_pct NOT computed here (requires per-ticker open prices).
    Default conservative: ELEVATED stays ELEVATED without gap information.
    """
    df = vix_daily_df.sort_values("date").reset_index(drop=True).copy()
    df["vix_prior_close"] = df["vix_close"].shift(1)
    df["date_et"] = df["date"].dt.date
    df["override_state"] = df["vix_prior_close"].apply(
        lambda v: derive_override_state(None if pd.isna(v) else float(v), gap_pct=None)
    )
    return df[["date_et", "vix_prior_close", "override_state"]]


def get_override_state_at(override_df: pd.DataFrame, d: date) -> str:
    """Lookup Override state for a specific date. Returns 'NORMAL' if no match."""
    matches = override_df[override_df["date_et"] == d]
    if matches.empty:
        return "NORMAL"
    return str(matches.iloc[0]["override_state"])
