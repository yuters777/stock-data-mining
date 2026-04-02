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

# ══════════════════════════════════════════════════════════════════════
# ANALYSIS MODE (--analysis flag)
# ══════════════════════════════════════════════════════════════════════

if "--analysis" not in sys.argv:
    sys.exit(0)

print("\n" + "=" * 60)
print("ANALYSIS & ROBUSTNESS")
print("=" * 60)


def calc_pf(rets):
    """Profit factor from a series of returns."""
    gains = rets[rets > 0].sum()
    losses = abs(rets[rets <= 0].sum())
    return gains / losses if losses > 0 else float("inf")


def run_spec_a_on_events(events_df, ticker_data, gap_col="abnormal_gap_pct",
                          gap_thresh=2.5, require_holds=True):
    """Run Spec A logic on a subset of events. Returns trades DataFrame."""
    mask = events_df[gap_col].abs() >= gap_thresh
    if require_holds:
        mask = mask & events_df["first_day_holds"]
    subset = events_df[mask]
    trades = []
    for _, row in subset.iterrows():
        ret, direction, exit_price, hold_days = compute_spec_a_b_return(row, ticker_data)
        if ret is not None:
            trades.append({
                "ticker": row["ticker"], "earnings_date": row["earnings_date"],
                "abnormal_gap_pct": row[gap_col], "raw_gap_pct": row.get("raw_gap_pct", None),
                "entry": row["reaction_close"], "exit": exit_price,
                "direction": direction, "return_pct": ret, "hold_days": hold_days,
                "revenue_confirms": row.get("revenue_confirms", None),
            })
    return pd.DataFrame(trades)


# ── ANALYSIS 1: Gap Threshold Sweep ───────────────────────────────────
print("\n--- ANALYSIS 1: Gap Threshold Sweep (Spec A structure) ---")
print(f"{'Gap%':>6} {'N':>5} {'Mean%':>7} {'WR%':>6} {'PF':>6}")
print("-" * 36)
for thresh in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
    tdf = run_spec_a_on_events(ev, ticker_data, gap_thresh=thresh)
    if len(tdf) == 0:
        print(f"{thresh:>6.1f} {'0':>5} {'--':>7} {'--':>6} {'--':>6}")
        continue
    r = tdf["return_pct"]
    print(f"{thresh:>6.1f} {len(r):>5} {r.mean():>7.2f} {(r>0).mean()*100:>6.1f} {calc_pf(r):>6.2f}")


# ── ANALYSIS 2: Drift Curve ──────────────────────────────────────────
print("\n--- ANALYSIS 2: Drift Curve (|abnormal_gap| >= 2%) ---")
drift_events = ev[ev["abnormal_gap_pct"].abs() >= 2.0].copy()

print(f"{'Days':>5} {'Mean_Drift%':>12} {'Hit_Rate%':>10}")
print("-" * 30)
for hold in [1, 2, 3, 5, 7, 10, 15, 20]:
    drifts = []
    for _, row in drift_events.iterrows():
        d = ticker_data[row["ticker"]]
        dd = get_trading_day(d, row["reaction_day"], hold)
        if dd is None:
            continue
        close_h = get_val(d, dd, "Close")
        if close_h is None or (isinstance(close_h, float) and np.isnan(close_h)):
            continue
        entry = row["reaction_close"]
        if entry == 0:
            continue
        ret = (close_h - entry) / entry * 100
        direction = 1 if row["abnormal_gap_pct"] > 0 else -1
        drifts.append(ret * direction)
    if len(drifts) == 0:
        print(f"{hold:>5} {'--':>12} {'--':>10}")
        continue
    arr = np.array(drifts)
    print(f"{hold:>5} {arr.mean():>12.3f} {(arr>0).mean()*100:>10.1f}")

drift_peak_day = None
drift_peak_val = -999
for hold in [1, 2, 3, 5, 7, 10, 15, 20]:
    drifts = []
    for _, row in drift_events.iterrows():
        d = ticker_data[row["ticker"]]
        dd = get_trading_day(d, row["reaction_day"], hold)
        if dd is None:
            continue
        close_h = get_val(d, dd, "Close")
        if close_h is None or (isinstance(close_h, float) and np.isnan(close_h)):
            continue
        entry = row["reaction_close"]
        if entry == 0:
            continue
        ret = (close_h - entry) / entry * 100
        direction = 1 if row["abnormal_gap_pct"] > 0 else -1
        drifts.append(ret * direction)
    if len(drifts) > 0:
        m = np.mean(drifts)
        if m > drift_peak_val:
            drift_peak_val = m
            drift_peak_day = hold


# ── ANALYSIS 3: Year-by-Year (Spec A) ────────────────────────────────
print("\n--- ANALYSIS 3: Year-by-Year (Spec A) ---")
if len(spec_a_df) > 0:
    spec_a_df["year"] = pd.to_datetime(spec_a_df["earnings_date"]).dt.year
    print(f"{'Year':>6} {'N':>5} {'Mean%':>7} {'WR%':>6} {'PF':>6}")
    print("-" * 36)
    years_negative = 0
    total_pnl = spec_a_df["return_pct"].sum()
    max_year_pnl_pct = 0
    for yr in sorted(spec_a_df["year"].unique()):
        sub = spec_a_df[spec_a_df["year"] == yr]
        r = sub["return_pct"]
        pf_yr = calc_pf(r)
        yr_pnl_pct = r.sum() / total_pnl * 100 if total_pnl != 0 else 0
        if r.mean() < 0:
            years_negative += 1
        max_year_pnl_pct = max(max_year_pnl_pct, abs(yr_pnl_pct))
        flag = " <<<" if abs(yr_pnl_pct) > 30 else ""
        print(f"{yr:>6} {len(r):>5} {r.mean():>7.2f} {(r>0).mean()*100:>6.1f} {pf_yr:>6.2f}{flag}")
    n_years = len(spec_a_df["year"].unique())
    years_positive = n_years - years_negative
    if years_negative > 0:
        print(f"  WARNING: {years_negative} year(s) negative")
    if max_year_pnl_pct > 30:
        print(f"  WARNING: single year contributes >{max_year_pnl_pct:.0f}% of total P&L")
else:
    years_positive = 0
    n_years = 0
    print("  No Spec A trades")


# ── ROBUSTNESS R1: Leave-One-Ticker-Out (Spec A) ─────────────────────
print("\n--- ROBUSTNESS R1: Leave-One-Ticker-Out (Spec A) ---")
if len(spec_a_df) > 0:
    base_pf = calc_pf(spec_a_df["return_pct"])
    print(f"Baseline PF: {base_pf:.2f}")
    print(f"{'Ticker':<8} {'N':>4} {'PF':>6} {'PF_chg%':>8}")
    print("-" * 30)
    loto_max_impact = 0
    loto_max_ticker = ""
    for tkr in sorted(spec_a_df["ticker"].unique()):
        sub = spec_a_df[spec_a_df["ticker"] != tkr]
        if len(sub) == 0:
            continue
        pf_loo = calc_pf(sub["return_pct"])
        chg = (pf_loo - base_pf) / base_pf * 100 if base_pf != 0 and base_pf != float("inf") else 0
        flag = " <<<" if abs(chg) > 20 else ""
        print(f"{tkr:<8} {len(sub):>4} {pf_loo:>6.2f} {chg:>8.1f}%{flag}")
        if abs(chg) > abs(loto_max_impact):
            loto_max_impact = chg
            loto_max_ticker = tkr
else:
    loto_max_impact = 0
    loto_max_ticker = "N/A"


# ── ROBUSTNESS R2: Leave-One-Year-Out (Spec A) ───────────────────────
print("\n--- ROBUSTNESS R2: Leave-One-Year-Out (Spec A) ---")
if len(spec_a_df) > 0:
    print(f"Baseline PF: {base_pf:.2f}")
    print(f"{'Year':>6} {'N':>4} {'PF':>6} {'PF_chg%':>8}")
    print("-" * 30)
    loyo_max_impact = 0
    loyo_max_year = ""
    for yr in [2022, 2023, 2024, 2025]:
        sub = spec_a_df[spec_a_df["year"] != yr]
        if len(sub) == 0:
            continue
        pf_loo = calc_pf(sub["return_pct"])
        chg = (pf_loo - base_pf) / base_pf * 100 if base_pf != 0 and base_pf != float("inf") else 0
        flag = " <<<" if abs(chg) > 25 else ""
        print(f"{yr:>6} {len(sub):>4} {pf_loo:>6.2f} {chg:>8.1f}%{flag}")
        if abs(chg) > abs(loyo_max_impact):
            loyo_max_impact = chg
            loyo_max_year = str(yr)
else:
    loyo_max_impact = 0
    loyo_max_year = "N/A"


# ── ROBUSTNESS R3: Sector Breakdown (Spec A) ─────────────────────────
print("\n--- ROBUSTNESS R3: Sector Breakdown (Spec A) ---")
SECTORS = {
    "mega_tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
    "growth_semi": ["TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM", "MU", "INTC"],
    "crypto_proxy": ["COIN", "MSTR", "MARA"],
    "finance": ["C", "GS", "V", "BA", "JPM"],
    "china_adr": ["BABA", "BIDU"],
    "consumer": ["COST"],
}
if len(spec_a_df) > 0:
    print(f"{'Sector':<14} {'N':>4} {'Mean%':>7} {'WR%':>6} {'PF':>6}")
    print("-" * 42)
    for sector, tkrs in SECTORS.items():
        sub = spec_a_df[spec_a_df["ticker"].isin(tkrs)]
        if len(sub) == 0:
            print(f"{sector:<14} {'0':>4} {'--':>7} {'--':>6} {'--':>6}")
            continue
        r = sub["return_pct"]
        print(f"{sector:<14} {len(r):>4} {r.mean():>7.2f} {(r>0).mean()*100:>6.1f} {calc_pf(r):>6.2f}")
else:
    print("  No Spec A trades")


# ── ROBUSTNESS R4: Abnormal vs Raw Gap ────────────────────────────────
print("\n--- ROBUSTNESS R4: Abnormal vs Raw Gap ---")
raw_df = run_spec_a_on_events(ev, ticker_data, gap_col="raw_gap_pct", gap_thresh=2.5)
print(f"{'Gap_Type':<12} {'N':>4} {'Mean%':>7} {'WR%':>6} {'PF':>6}")
print("-" * 40)
if len(spec_a_df) > 0:
    r_abn = spec_a_df["return_pct"]
    print(f"{'Abnormal':<12} {len(r_abn):>4} {r_abn.mean():>7.2f} {(r_abn>0).mean()*100:>6.1f} {calc_pf(r_abn):>6.2f}")
else:
    print(f"{'Abnormal':<12} {'0':>4} {'--':>7} {'--':>6} {'--':>6}")
if len(raw_df) > 0:
    r_raw = raw_df["return_pct"]
    print(f"{'Raw':<12} {len(r_raw):>4} {r_raw.mean():>7.2f} {(r_raw>0).mean()*100:>6.1f} {calc_pf(r_raw):>6.2f}")
    raw_pf = calc_pf(r_raw)
else:
    print(f"{'Raw':<12} {'0':>4} {'--':>7} {'--':>6} {'--':>6}")
    raw_pf = 0
abn_pf = calc_pf(spec_a_df["return_pct"]) if len(spec_a_df) > 0 else 0
abnormal_lift = f"{abn_pf:.2f} vs {raw_pf:.2f}"


# ── ROBUSTNESS R5: Revenue Confirmation Lift ──────────────────────────
print("\n--- ROBUSTNESS R5: Revenue Confirmation Lift ---")
if len(spec_a_df) > 0:
    # Merge revenue_confirms back onto spec_a trades
    # We need to match by ticker+earnings_date from the events DataFrame
    spec_a_with_rev = spec_a_df.merge(
        ev[["ticker", "earnings_date", "revenue_confirms"]],
        on=["ticker", "earnings_date"], how="left"
    )
    print(f"{'Revenue':<14} {'N':>4} {'Mean%':>7} {'WR%':>6} {'PF':>6}")
    print("-" * 40)
    for label, val in [("Confirms", True), ("Contradicts", False)]:
        sub = spec_a_with_rev[spec_a_with_rev["revenue_confirms"] == val]
        if len(sub) == 0:
            print(f"{label:<14} {'0':>4} {'--':>7} {'--':>6} {'--':>6}")
            continue
        r = sub["return_pct"]
        print(f"{label:<14} {len(r):>4} {r.mean():>7.2f} {(r>0).mean()*100:>6.1f} {calc_pf(r):>6.2f}")
    confirms_pf = calc_pf(spec_a_with_rev[spec_a_with_rev["revenue_confirms"] == True]["return_pct"]) \
        if (spec_a_with_rev["revenue_confirms"] == True).any() else 0
    contradicts_pf = calc_pf(spec_a_with_rev[spec_a_with_rev["revenue_confirms"] == False]["return_pct"]) \
        if (spec_a_with_rev["revenue_confirms"] == False).any() else 0
else:
    confirms_pf = 0
    contradicts_pf = 0
    print("  No Spec A trades")


# ── FINAL VERDICT ─────────────────────────────────────────────────────

# Gather spec stats
def spec_stats(df):
    if len(df) == 0:
        return {"N": 0, "WR": 0, "PF": 0, "p": None}
    r = df["return_pct"]
    pf = calc_pf(r)
    wr = (r > 0).mean() * 100
    pval = ttest_1samp(r, 0).pvalue if HAS_SCIPY and len(r) >= 2 else None
    return {"N": len(r), "WR": wr, "PF": pf, "p": pval}

sa = spec_stats(spec_a_df)
sb = spec_stats(spec_b_df)
sc = spec_stats(spec_c_df)

def verdict(stats, loto_ok=True, loyo_ok=True):
    """VALIDATED if N>=30, WR>=55%, PF>=1.5, LOTO<20%, LOYO<25%.
       MARGINAL if close. REJECTED otherwise."""
    n_ok = stats["N"] >= 30
    wr_ok = stats["WR"] >= 55
    pf_ok = stats["PF"] >= 1.5
    if n_ok and wr_ok and pf_ok and loto_ok and loyo_ok:
        return "VALIDATED"
    # Marginal: at least 2 of 3 core thresholds met, and N >= 15
    core_met = sum([wr_ok, pf_ok]) + (1 if n_ok else (1 if stats["N"] >= 15 else 0))
    if core_met >= 2 and stats["N"] >= 10:
        return "MARGINAL"
    return "REJECTED"

loto_ok = abs(loto_max_impact) < 20
loyo_ok = abs(loyo_max_impact) < 25

print("\n" + "=" * 60)
print("=== Daily PEAD Redesign — Final Results ===")
print("=" * 60)

def fmt_p(p):
    return f"{p:.4f}" if p is not None else "N/A"

print(f"\nSpec A (Price-Only):     N={sa['N']}, WR={sa['WR']:.1f}%, PF={sa['PF']:.2f}, p={fmt_p(sa['p'])}")
print(f"Spec B (EPS+Revenue):    N={sb['N']}, WR={sb['WR']:.1f}%, PF={sb['PF']:.2f}, p={fmt_p(sb['p'])}")
print(f"Spec C (Minimal):        N={sc['N']}, WR={sc['WR']:.1f}%, PF={sc['PF']:.2f}, p={fmt_p(sc['p'])}")

print(f"\nDrift peak: day {drift_peak_day} (+{drift_peak_val:.2f}%)")
print(f"Abnormal vs Raw lift: {abnormal_lift}")

print(f"\nRobustness:")
print(f"  LOTO max: {abs(loto_max_impact):.1f}% (ticker: {loto_max_ticker})")
print(f"  LOYO max: {abs(loyo_max_impact):.1f}% (year: {loyo_max_year})")
print(f"  Revenue lift: confirms PF={confirms_pf:.2f} vs contradicts PF={contradicts_pf:.2f}")
print(f"  Years positive: {years_positive}/{n_years}")

v_a = verdict(sa, loto_ok, loyo_ok)
v_b = verdict(sb)  # LOTO/LOYO only computed for Spec A
v_c = verdict(sc)

print(f"\nVERDICT:")
print(f"  Spec A: {v_a}")
print(f"  Spec B: {v_b}")
print(f"  Spec C: {v_c}")

print(f"\nThresholds: N>=30, WR>=55%, PF>=1.5, LOTO<20%, LOYO<25%")
print("=" * 60)
