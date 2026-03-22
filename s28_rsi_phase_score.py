"""S28 RSI Phase Scoring — Core Functions.

Implements the RSI Phase Scoring curve from S28 DR (ChatGPT Pro, 9.0/10).
Constants are FIXED from the design review — do NOT optimize.
"""

import math
import numpy as np


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def rsi_phase_score(rsi: float, rsi_slope: float, direction: str) -> float:
    """
    RSI phase score for EMA 9/21 cross entries.

    Parameters
    ----------
    rsi : float — RSI(14) at entry bar, 0..100
    rsi_slope : float — 5-bar OLS slope of RSI, RSI points per bar
    direction : str — "LONG" or "SHORT"

    Returns
    -------
    float — Score in [0.0, 1.0]
    """
    d = direction.upper()
    if d == "LONG":
        x = float(rsi)
        m = float(rsi_slope)
    elif d == "SHORT":
        x = 100.0 - float(rsi)
        m = -float(rsi_slope)
    else:
        raise ValueError("direction must be 'LONG' or 'SHORT'")

    level = (
        _sigmoid((x - 28.0) / 4.5) *
        _sigmoid((68.0 - x) / 5.0)
    ) / 0.9710

    slope_factor = 0.05 + 0.95 * _sigmoid((m - 0.10) / 0.65)

    score = level * slope_factor
    return max(0.0, min(1.0, score))


def rsi_ols_slope(last_5_rsi: list[float]) -> float:
    """5-bar OLS slope of RSI in RSI points per bar."""
    y = np.asarray(last_5_rsi, dtype=float)
    x = np.arange(len(y), dtype=float)
    x_mean = x.mean()
    y_mean = y.mean()
    num = ((x - x_mean) * (y - y_mean)).sum()
    den = ((x - x_mean) ** 2).sum()
    return float(num / den)


def classify_rsi_phase(rsi: float, rsi_slope: float, direction: str) -> str:
    """Classify entry into discrete RSI phase labels.

    Long phases (L1-L6):
      L1: RSI < 30 (oversold entry)
      L2: 30 <= RSI < 40, slope > 0 (recovery launch)
      L3: 40 <= RSI < 55, slope > 0 (momentum sweet spot)
      L4: 55 <= RSI < 65, slope > 0 (late momentum)
      L5: RSI >= 65 (overbought entry)
      L6: slope <= 0 (fading momentum, any RSI)

    Short phases mirror around 50.
    """
    d = direction.upper()
    if d == "LONG":
        x, m = rsi, rsi_slope
        prefix = "L"
    elif d == "SHORT":
        x, m = 100.0 - rsi, -rsi_slope
        prefix = "S"
    else:
        raise ValueError("direction must be 'LONG' or 'SHORT'")

    if m <= 0:
        return f"{prefix}6"
    if x < 30:
        return f"{prefix}1"
    if x < 40:
        return f"{prefix}2"
    if x < 55:
        return f"{prefix}3"
    if x < 65:
        return f"{prefix}4"
    return f"{prefix}5"


# ── Indicator helpers (reused from repo conventions) ──

def ema(values, period):
    """Exponential moving average."""
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    out[period - 1] = np.mean(values[:period])
    k = 2.0 / (period + 1)
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def rsi_wilder(closes, period=14):
    """RSI with Wilder (exponential) smoothing."""
    n = len(closes)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i + 1] = 100.0
        else:
            out[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


# ── Sanity check ──

if __name__ == "__main__":
    test_cases = [
        ("LONG",  35, +1.2, 0.72),
        ("LONG",  42, +0.8, 0.74),
        ("LONG",  50,  0.0, 0.49),
        ("LONG",  58, +0.5, 0.60),
        ("LONG",  65, +0.8, 0.50),
        ("LONG",  72, +1.0, 0.26),
        ("LONG",  45, -1.0, 0.20),
        ("LONG",  22, +2.0, 0.20),
        ("SHORT", 65, -0.6, 0.59),
        ("SHORT", 28, -1.2, 0.27),
    ]

    print("S28 RSI Phase Score — Sanity Check")
    print("=" * 65)
    print(f"{'Dir':<6} {'RSI':>4} {'Slope':>6} {'Expected':>9} {'Actual':>8} {'Delta':>7} {'OK?'}")
    print("-" * 65)

    all_ok = True
    for direction, rsi_val, slope, expected in test_cases:
        actual = rsi_phase_score(rsi_val, slope, direction)
        delta = actual - expected
        ok = abs(delta) <= 0.05
        if not ok:
            all_ok = False
        print(f"{direction:<6} {rsi_val:>4} {slope:>+6.1f} {expected:>9.2f} {actual:>8.4f} {delta:>+7.4f} {'✓' if ok else '✗ FAIL'}")

    print("-" * 65)
    if all_ok:
        print("ALL SANITY CHECKS PASSED — proceeding.")
    else:
        print("SANITY CHECK FAILED — STOP and investigate.")

    # Also test rsi_ols_slope
    print("\nOLS slope test: [40, 42, 44, 46, 48] → expected 2.0")
    print(f"  Actual: {rsi_ols_slope([40, 42, 44, 46, 48]):.4f}")
