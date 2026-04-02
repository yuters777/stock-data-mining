"""
PEAD Daily Backtest — Three Confirmatory Specs (Pre-Registered)

Specs:
  A: Price-Only (|abnormal_gap| >= 2.5%, first_day_holds, no EPS filter)
  B: Enriched   (Spec A + |eps_surprise_pct| >= 10% + revenue confirms)
  C: Minimal    (|abnormal_gap| >= 2.0%, no holds filter, 5-day fixed hold)
"""

import os
import sys
import numpy as np
import pandas as pd
from pathlib import Path

try:
    from scipy.stats import ttest_1samp
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# ── paths ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "backtester" / "data" / "daily"
EARNINGS_PATH = ROOT / "backtester" / "data" / "fmp_earnings.csv"
OUTPUT_DIR = ROOT / "backtest_output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── STEP 1: Load Data ─────────────────────────────────────────────────

def load_daily(ticker):
    """Load daily OHLCV for a ticker (yfinance multi-header format)."""
    path = DAILY_DIR / f"{ticker}_daily.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)
    # Flatten multi-index columns: take first level (Price type)
    df.columns = df.columns.get_level_values(0)
    df = df.sort_index()
    # Ensure numeric
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

# Load SPY
spy = load_daily("SPY")
assert spy is not None, "SPY daily data required"

# Discover tickers from daily directory (exclude SPY)
daily_files = list(DAILY_DIR.glob("*_daily.csv"))
tickers = sorted(set(f.stem.replace("_daily", "") for f in daily_files) - {"SPY"})

# Load all ticker data
ticker_data = {}
for t in tickers:
    d = load_daily(t)
    if d is not None:
        ticker_data[t] = d

print(f"Loaded {len(ticker_data)} tickers + SPY")

# Load earnings
earnings = pd.read_csv(EARNINGS_PATH)
earnings["earnings_date"] = pd.to_datetime(earnings["earnings_date"])
earnings["time_of_day"] = earnings["time_of_day"].fillna("amc").str.lower().str.strip()

# Filter: eps_actual not null, ticker has daily data, earnings_date within range
earnings = earnings[earnings["eps_actual"].notna()].copy()
earnings = earnings[earnings["ticker"].isin(ticker_data)].copy()

def in_range(row):
    d = ticker_data[row["ticker"]]
    return d.index.min() <= row["earnings_date"] <= d.index.max()

earnings = earnings[earnings.apply(in_range, axis=1)].copy()
print(f"Qualifying earnings events: {len(earnings)}")

# ── STEP 2: Build Events ──────────────────────────────────────────────

def get_trading_day(df, date, offset):
    """Get the trading day at `offset` positions from `date` in df's index.
    offset=0 returns the date itself (or next available), offset=1 returns next, etc.
    offset=-1 returns the prior trading day."""
    idx = df.index
    # Find the position of the closest date >= given date
    mask = idx >= date
    if offset >= 0:
        if not mask.any():
            return None
        pos = mask.argmax()  # first True
        target = pos + offset
    else:
        # For negative offset, find last date <= given date
        mask_le = idx <= date
        if not mask_le.any():
            return None
        pos = len(idx) - 1 - mask_le[::-1].argmax()
        target = pos + offset
    if 0 <= target < len(idx):
        return idx[target]
    return None

def get_val(df, date, col):
    if date is None or date not in df.index:
        return None
    return df.loc[date, col]

events = []
for _, row in earnings.iterrows():
    tkr = row["ticker"]
    ed = row["earnings_date"]
    tod = row["time_of_day"]
    d = ticker_data[tkr]

    if tod == "bmo":
        # BMO: prior_close = day before earnings_date, next_open = earnings_date open
        day_before = get_trading_day(d, ed, -1)
        reaction_day = get_trading_day(d, ed, 0)
        prior_close = get_val(d, day_before, "Close")
        next_open = get_val(d, reaction_day, "Open")
        spy_prior = get_val(spy, day_before, "Close")
        spy_next_open = get_val(spy, reaction_day, "Open")
    else:
        # AMC (or null): prior_close = earnings_date close, next_open = next day open
        ed_in_data = get_trading_day(d, ed, 0)
        next_day = get_trading_day(d, ed, 1)
        reaction_day = next_day
        prior_close = get_val(d, ed_in_data, "Close")
        next_open = get_val(d, next_day, "Open")
        spy_prior = get_val(spy, ed_in_data, "Close")
        spy_next_open = get_val(spy, next_day, "Open")

    # Skip if any key value missing
    if any(v is None or (isinstance(v, float) and np.isnan(v))
           for v in [prior_close, next_open, spy_prior, spy_next_open, reaction_day]):
        continue

    raw_gap_pct = (next_open - prior_close) / prior_close * 100
    spy_gap_pct = (spy_next_open - spy_prior) / spy_prior * 100
    abnormal_gap_pct = raw_gap_pct - spy_gap_pct
    gap_midpoint = (prior_close + next_open) / 2

    # Reaction day stats
    reaction_close = get_val(d, reaction_day, "Close")
    reaction_high = get_val(d, reaction_day, "High")
    reaction_low = get_val(d, reaction_day, "Low")
    if any(v is None or (isinstance(v, float) and np.isnan(v))
           for v in [reaction_close, reaction_high, reaction_low]):
        continue
    reaction_mid = (reaction_high + reaction_low) / 2

    # First day holds
    if abnormal_gap_pct > 0:
        first_day_holds = (reaction_close > prior_close) and (reaction_close >= reaction_mid)
    else:
        first_day_holds = (reaction_close < prior_close) and (reaction_close <= reaction_mid)

    # Revenue confirmation
    eps_surp = row["eps_surprise_pct"]
    rev_surp = row["revenue_surprise_pct"]
    if pd.notna(eps_surp) and pd.notna(rev_surp) and eps_surp != 0 and rev_surp != 0:
        revenue_confirms = (eps_surp > 0 and rev_surp > 0) or (eps_surp < 0 and rev_surp < 0)
    else:
        revenue_confirms = False

    # Drift closes: day+1, +3, +5, +10 after reaction_day
    drift = {}
    for offset in [1, 3, 5, 10]:
        dd = get_trading_day(d, reaction_day, offset)
        drift[f"close_d{offset}"] = get_val(d, dd, "Close") if dd is not None else None

    # Entry for Spec C: next day open after reaction_day
    day_after_reaction = get_trading_day(d, reaction_day, 1)
    spec_c_entry = get_val(d, day_after_reaction, "Open") if day_after_reaction is not None else None

    # Spec C exit: close 5 trading days after entry day (day_after_reaction)
    if day_after_reaction is not None:
        spec_c_exit_day = get_trading_day(d, day_after_reaction, 5)
        spec_c_exit = get_val(d, spec_c_exit_day, "Close") if spec_c_exit_day is not None else None
    else:
        spec_c_exit = None

    events.append({
        "ticker": tkr,
        "earnings_date": ed,
        "time_of_day": tod,
        "eps_surprise_pct": eps_surp,
        "revenue_surprise_pct": rev_surp,
        "prior_close": prior_close,
        "next_open": next_open,
        "raw_gap_pct": raw_gap_pct,
        "spy_gap_pct": spy_gap_pct,
        "abnormal_gap_pct": abnormal_gap_pct,
        "gap_midpoint": gap_midpoint,
        "reaction_day": reaction_day,
        "reaction_close": reaction_close,
        "reaction_high": reaction_high,
        "reaction_low": reaction_low,
        "reaction_mid": reaction_mid,
        "first_day_holds": first_day_holds,
        "revenue_confirms": revenue_confirms,
        **drift,
        "spec_c_entry": spec_c_entry,
        "spec_c_exit": spec_c_exit,
    })

ev = pd.DataFrame(events)
print(f"\nEvents with daily data: {len(ev)}")
print(f"|abnormal_gap| >= 2%: {(ev['abnormal_gap_pct'].abs() >= 2).sum()}")
print(f"|abnormal_gap| >= 2.5%: {(ev['abnormal_gap_pct'].abs() >= 2.5).sum()}")
print(f"|abnormal_gap| >= 3%: {(ev['abnormal_gap_pct'].abs() >= 3).sum()}")
print(f"Revenue confirms: {ev['revenue_confirms'].sum()} ({ev['revenue_confirms'].mean()*100:.1f}%)")
mask_25 = ev["abnormal_gap_pct"].abs() >= 2.5
print(f"First day holds (abnormal >= 2.5%): {ev.loc[mask_25, 'first_day_holds'].sum()} "
      f"({ev.loc[mask_25, 'first_day_holds'].mean()*100:.1f}%)")


# ── STEP 3: Run Three Specs ───────────────────────────────────────────

def compute_spec_a_b_return(row, ticker_data):
    """Spec A/B: entry=reaction_close, exit=close crosses gap_midpoint or 10d max."""
    tkr = row["ticker"]
    d = ticker_data[tkr]
    direction = 1 if row["abnormal_gap_pct"] > 0 else -1
    entry = row["reaction_close"]
    gap_mid = row["gap_midpoint"]
    reaction_day = row["reaction_day"]

    # Walk up to 10 days after reaction_day
    exit_price = None
    exit_day = None
    for i in range(1, 11):
        dd = get_trading_day(d, reaction_day, i)
        if dd is None:
            break
        close_i = get_val(d, dd, "Close")
        if close_i is None or (isinstance(close_i, float) and np.isnan(close_i)):
            break
        # Check if close crosses gap_midpoint against position
        if direction == 1 and close_i <= gap_mid:
            exit_price = close_i
            exit_day = dd
            break
        elif direction == -1 and close_i >= gap_mid:
            exit_price = close_i
            exit_day = dd
            break
        # Track last valid for max hold
        exit_price = close_i
        exit_day = dd

    if exit_price is None or entry == 0:
        return None, None, None, None

    ret = (exit_price - entry) / entry * 100
    if direction == -1:
        ret = -ret
    hold_days = None
    if exit_day is not None and reaction_day is not None:
        # Count trading days between reaction_day and exit_day
        idx = d.index
        mask = (idx > reaction_day) & (idx <= exit_day)
        hold_days = mask.sum()
    return ret, direction, exit_price, hold_days


def print_spec_results(name, trades_df):
    if len(trades_df) == 0:
        print(f"\n=== {name} ===\nN: 0 — no trades\n")
        return
    rets = trades_df["return_pct"].dropna()
    n = len(rets)
    mean_r = rets.mean()
    med_r = rets.median()
    wr = (rets > 0).mean() * 100
    gains = rets[rets > 0].sum()
    losses = abs(rets[rets <= 0].sum())
    pf = gains / losses if losses > 0 else float("inf")
    if HAS_SCIPY and n >= 2:
        _, pval = ttest_1samp(rets, 0)
    else:
        pval = None

    print(f"\n=== {name} ===")
    print(f"N: {n}")
    print(f"Mean return: {mean_r:.2f}%")
    print(f"Median return: {med_r:.2f}%")
    print(f"Win rate: {wr:.1f}%")
    print(f"Profit factor: {pf:.2f}")
    print(f"p-value: {pval:.4f}" if pval is not None else "p-value: N/A (scipy not available)")

    for label, dirval in [("LONG", 1), ("SHORT", -1)]:
        sub = trades_df[trades_df["direction"] == dirval]
        if len(sub) == 0:
            print(f"{label}:  N=0")
            continue
        sr = sub["return_pct"].dropna()
        print(f"{label}:  N={len(sr)}, mean={sr.mean():.2f}%, WR={((sr>0).mean()*100):.1f}%")

    return {"name": name, "N": n, "Mean%": f"{mean_r:.2f}", "WR%": f"{wr:.1f}",
            "PF": f"{pf:.2f}", "p-value": f"{pval:.4f}" if pval is not None else "N/A"}


# ── SPEC A: Price-Only ─────────────────────────────────────────────────
mask_a = (ev["abnormal_gap_pct"].abs() >= 2.5) & (ev["first_day_holds"])
spec_a_events = ev[mask_a].copy()

spec_a_trades = []
for _, row in spec_a_events.iterrows():
    ret, direction, exit_price, hold_days = compute_spec_a_b_return(row, ticker_data)
    if ret is not None:
        spec_a_trades.append({
            "spec": "A", "ticker": row["ticker"],
            "earnings_date": row["earnings_date"],
            "abnormal_gap_pct": row["abnormal_gap_pct"],
            "entry": row["reaction_close"], "exit": exit_price,
            "direction": direction, "return_pct": ret, "hold_days": hold_days,
        })
spec_a_df = pd.DataFrame(spec_a_trades)

# ── SPEC B: Enriched ──────────────────────────────────────────────────
mask_b = (mask_a
          & (ev["eps_surprise_pct"].abs() >= 10)
          & (ev["revenue_confirms"]))
spec_b_events = ev[mask_b].copy()

spec_b_trades = []
for _, row in spec_b_events.iterrows():
    ret, direction, exit_price, hold_days = compute_spec_a_b_return(row, ticker_data)
    if ret is not None:
        spec_b_trades.append({
            "spec": "B", "ticker": row["ticker"],
            "earnings_date": row["earnings_date"],
            "abnormal_gap_pct": row["abnormal_gap_pct"],
            "eps_surprise_pct": row["eps_surprise_pct"],
            "revenue_surprise_pct": row["revenue_surprise_pct"],
            "entry": row["reaction_close"], "exit": exit_price,
            "direction": direction, "return_pct": ret, "hold_days": hold_days,
        })
spec_b_df = pd.DataFrame(spec_b_trades)

# ── SPEC C: Minimal ───────────────────────────────────────────────────
mask_c = ev["abnormal_gap_pct"].abs() >= 2.0
spec_c_events = ev[mask_c].copy()

spec_c_trades = []
for _, row in spec_c_events.iterrows():
    entry = row["spec_c_entry"]
    exit_price = row["spec_c_exit"]
    if entry is None or exit_price is None:
        continue
    if isinstance(entry, float) and np.isnan(entry):
        continue
    if isinstance(exit_price, float) and np.isnan(exit_price):
        continue
    if entry == 0:
        continue
    direction = 1 if row["abnormal_gap_pct"] > 0 else -1
    ret = (exit_price - entry) / entry * 100
    if direction == -1:
        ret = -ret
    spec_c_trades.append({
        "spec": "C", "ticker": row["ticker"],
        "earnings_date": row["earnings_date"],
        "abnormal_gap_pct": row["abnormal_gap_pct"],
        "entry": entry, "exit": exit_price,
        "direction": direction, "return_pct": ret, "hold_days": 5,
    })
spec_c_df = pd.DataFrame(spec_c_trades)

# ── Print Results ──────────────────────────────────────────────────────
summaries = []
summaries.append(print_spec_results("SPEC A: Price-Only", spec_a_df))
summaries.append(print_spec_results("SPEC B: Enriched", spec_b_df))
summaries.append(print_spec_results("SPEC C: Minimal", spec_c_df))

# Comparison table
print("\n" + "=" * 55)
print(f"{'Spec':<22} {'N':>4} {'Mean%':>7} {'WR%':>6} {'PF':>6} {'p-value':>8}")
print("-" * 55)
for s in summaries:
    if s is not None:
        print(f"{s['name']:<22} {s['N']:>4} {s['Mean%']:>7} {s['WR%']:>6} {s['PF']:>6} {s['p-value']:>8}")
print("=" * 55)

# ── Save Trades ────────────────────────────────────────────────────────
all_trades = pd.concat([spec_a_df, spec_b_df, spec_c_df], ignore_index=True)
out_path = OUTPUT_DIR / "pead_daily_trades.csv"
all_trades.to_csv(out_path, index=False)
print(f"\nTrades saved to {out_path}")
