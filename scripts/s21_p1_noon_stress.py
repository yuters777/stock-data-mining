#!/usr/bin/env python3
"""S21-P1: Replace full-day look-ahead stress flag with as-of-noon return.

The S20 battery used end-of-day median return to tag stress days —
a look-ahead bias because intraday strategies cannot know the close
at decision time.  This script builds two bias-free alternatives:

  1. Median-of-25-tickers as-of-noon return  (< -0.75%)
  2. SPY as-of-noon return                   (< -1.00%)
"""

import json
import pathlib
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT  = ROOT / "backtest_output"

TRADE_UNIVERSE = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN", "COST",
    "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU", "NVDA",
    "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

NOON_THRESHOLD_MEDIAN = -0.0075   # -0.75 %
NOON_THRESHOLD_SPY    = -0.0100   # -1.00 %


# ── helpers ──────────────────────────────────────────────────────────────
def _load_m5(ticker: str) -> pd.DataFrame:
    fp = OUT / f"{ticker}_m5_regsess.csv"
    df = pd.read_csv(fp, parse_dates=["Datetime"])
    df["date"] = df["Datetime"].dt.date
    df["time"] = df["Datetime"].dt.time
    return df


def _noon_return(df: pd.DataFrame) -> pd.Series:
    """Return (price@12:00 / price@09:30) - 1 per trading day."""
    from datetime import time as T
    open_bars = df[df["time"] == T(9, 30)].set_index("date")["Close"]
    noon_bars = df[df["time"] == T(12, 0)].set_index("date")["Close"]
    common = open_bars.index.intersection(noon_bars.index)
    return (noon_bars.loc[common] / open_bars.loc[common]) - 1


# ── 1. ticker-median noon returns ────────────────────────────────────────
print("Loading M5 data for 25 tickers …")
noon_rets = {}
for tkr in TRADE_UNIVERSE:
    df = _load_m5(tkr)
    noon_rets[tkr] = _noon_return(df)

noon_df = pd.DataFrame(noon_rets)
median_noon = noon_df.median(axis=1)
median_noon.index = pd.to_datetime(median_noon.index)

stress_noon_mask = median_noon < NOON_THRESHOLD_MEDIAN
stress_noon_dates = sorted(
    median_noon[stress_noon_mask].index.strftime("%Y-%m-%d").tolist()
)

(OUT / "stress_noon_days.json").write_text(
    json.dumps(stress_noon_dates, indent=2) + "\n"
)

# ── 2. SPY-based noon stress ────────────────────────────────────────────
spy_df = _load_m5("SPY")
spy_noon = _noon_return(spy_df)
spy_noon.index = pd.to_datetime(spy_noon.index)

stress_spy_mask = spy_noon < NOON_THRESHOLD_SPY
stress_spy_dates = sorted(
    spy_noon[stress_spy_mask].index.strftime("%Y-%m-%d").tolist()
)

(OUT / "stress_noon_spy.json").write_text(
    json.dumps(stress_spy_dates, indent=2) + "\n"
)

# ── 3. comparison with original Level D ──────────────────────────────────
orig = set(json.loads((OUT / "stress_days.json").read_text()))
noon_set = set(stress_noon_dates)
spy_set  = set(stress_spy_dates)

overlap_noon = orig & noon_set
overlap_spy  = orig & spy_set

fp_noon = noon_set - orig      # flagged by noon but not orig
fn_noon = orig - noon_set      # missed by noon vs orig
fp_spy  = spy_set - orig
fn_spy  = orig - spy_set

print("\n" + "=" * 60)
print("S21-P1  Noon-Stress Bias-Free Replacement")
print("=" * 60)

print(f"\nOriginal Level D stress days (full-day median < -1.0%): {len(orig)}")
print(f"\n── Median-of-25 as-of-noon (< -0.75%) ──")
print(f"  Stress-noon days:   {len(noon_set)}")
print(f"  Overlap with orig:  {len(overlap_noon)}  "
      f"({100*len(overlap_noon)/len(orig):.1f}% of original)")
print(f"  False positives:    {len(fp_noon)}  (noon-only, not in orig)")
print(f"  False negatives:    {len(fn_noon)}  (orig-only, missed by noon)")

print(f"\n── SPY as-of-noon (< -1.0%) ──")
print(f"  Stress-SPY days:    {len(spy_set)}")
print(f"  Overlap with orig:  {len(overlap_spy)}  "
      f"({100*len(overlap_spy)/len(orig):.1f}% of original)")
print(f"  False positives:    {len(fp_spy)}  (SPY-only, not in orig)")
print(f"  False negatives:    {len(fn_spy)}  (orig-only, missed by SPY)")

# Jaccard similarity
j_noon = len(overlap_noon) / len(orig | noon_set) if (orig | noon_set) else 0
j_spy  = len(overlap_spy)  / len(orig | spy_set)  if (orig | spy_set)  else 0
print(f"\n  Jaccard similarity (noon-median): {j_noon:.3f}")
print(f"  Jaccard similarity (noon-SPY):    {j_spy:.3f}")

print(f"\nSaved: backtest_output/stress_noon_days.json  ({len(noon_set)} days)")
print(f"Saved: backtest_output/stress_noon_spy.json   ({len(spy_set)} days)")
print("=" * 60)
