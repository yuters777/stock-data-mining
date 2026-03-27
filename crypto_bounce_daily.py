#!/usr/bin/env python3
"""
Crypto Consecutive Down Days → Bounce Probability Study (Daily)

For BTC and ETH, compute daily returns from M5 bars (last bar of calendar day),
identify consecutive down-day streaks, and measure bounce probability
split by VIX regime and RSI.

No lookahead: VIX uses prior equity trading day's close.
Crypto trades 24/7 — all M5 bars used, no session filter.
"""

import os
import sys
import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_DIR = "data"
OUTPUT_DIR = "backtest_output/crypto_bounce_daily"
os.makedirs(OUTPUT_DIR, exist_ok=True)

TICKERS = ["BTC", "ETH"]
STREAK_BINS = [2, 3, 4, 5, "6+"]
VIX_BINS = [(0, 16, "<16"), (16, 20, "16-20"), (20, 25, "20-25"), (25, 999, ">=25")]
RSI_BINS = [(0, 30, "<30"), (30, 50, "30-50"), (50, 100, ">50")]

np.random.seed(123)  # for reproducible split-sample


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------
def load_m5(ticker):
    """Load M5 crypto data and derive daily OHLC."""
    path = os.path.join(DATA_DIR, f"{ticker}_crypto_data.csv")
    if not os.path.exists(path):
        print(f"ERROR: {path} not found. Run backfill_crypto.py or generate_synthetic_crypto.py first.")
        sys.exit(1)

    df = pd.read_csv(path, parse_dates=["Datetime"])
    df = df.sort_values("Datetime").reset_index(drop=True)

    # Print first/last 5 timestamps
    print(f"\n{'='*60}")
    print(f"{ticker} M5 data: {len(df)} bars")
    print(f"First 5 timestamps:")
    for _, row in df.head(5).iterrows():
        print(f"  {row['Datetime']}  Close={row['Close']:.2f}")
    print(f"Last 5 timestamps:")
    for _, row in df.tail(5).iterrows():
        print(f"  {row['Datetime']}  Close={row['Close']:.2f}")
    print(f"{'='*60}")

    # Daily close = last M5 bar of calendar day
    # Daily open = first M5 bar of calendar day
    df["date"] = df["Datetime"].dt.date
    daily_close = df.groupby("date")["Close"].last()
    daily_open = df.groupby("date")["Open"].first()
    daily_high = df.groupby("date")["High"].max()
    daily_low = df.groupby("date")["Low"].min()

    daily = pd.DataFrame({
        "open": daily_open,
        "high": daily_high,
        "low": daily_low,
        "close": daily_close,
    })
    daily.index = pd.DatetimeIndex(daily.index)
    daily = daily.sort_index()

    # Daily return (close-to-close)
    daily["ret"] = daily["close"].pct_change()

    return daily


def load_vix():
    """Load VIX daily data. Returns Series indexed by date."""
    path = os.path.join(DATA_DIR, "VIX_daily.csv")
    if not os.path.exists(path):
        print(f"WARNING: {path} not found. VIX regime analysis will be skipped.")
        return None
    vix = pd.read_csv(path, parse_dates=["Date"])
    vix = vix.set_index("Date").sort_index()
    vix.index = pd.DatetimeIndex(vix.index)
    return vix["Close"]


def compute_rsi(closes, period=14):
    """Compute RSI(14) from daily close series."""
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def get_prior_vix(vix_series, date):
    """Get prior equity trading day VIX close (no lookahead)."""
    if vix_series is None:
        return np.nan
    prior = vix_series[vix_series.index < date]
    if len(prior) == 0:
        return np.nan
    return prior.iloc[-1]


def classify_vix(val):
    """Classify VIX value into bucket."""
    if np.isnan(val):
        return None
    for lo, hi, label in VIX_BINS:
        if lo <= val < hi:
            return label
    return None


def classify_rsi(val):
    """Classify RSI value into bucket."""
    if np.isnan(val):
        return None
    for lo, hi, label in RSI_BINS:
        if lo <= val < hi:
            return label
    return None


# ---------------------------------------------------------------------------
# Streak Detection
# ---------------------------------------------------------------------------
def find_streaks(daily):
    """Find consecutive down-day streaks and their endpoints.

    Returns DataFrame with columns:
        date, streak_len, next_1d_ret, max_bounce_3d, rsi, close
    """
    daily = daily.copy()
    daily["down"] = (daily["ret"] < 0).astype(int)
    daily["rsi"] = compute_rsi(daily["close"])

    # Compute streak lengths (running count of consecutive down days)
    streaks = []
    current_streak = 0
    for i in range(len(daily)):
        if daily["down"].iloc[i] == 1:
            current_streak += 1
        else:
            current_streak = 0
        streaks.append(current_streak)
    daily["streak"] = streaks

    results = []
    dates = daily.index.tolist()

    for i in range(len(daily)):
        streak_len = daily["streak"].iloc[i]
        if streak_len < 2:
            continue

        # Check this is a streak endpoint: next day is NOT down, or is last day
        # Actually, we want the endpoint of each streak of length N
        # A bar with streak=N is an endpoint if next bar has streak=0 or streak=N+1
        # We want to capture at every streak length, not just endpoints
        # Better: for streak endpoint (where streak resets), record the max streak length
        # But we also need N=2,3,4,5,6+ separately

        # Instead: mark streak endpoints (next day is not down or is last day)
        is_endpoint = (i == len(daily) - 1) or (daily["streak"].iloc[i + 1] == 0)
        # Also capture intermediate points (e.g., day 3 of a 5-day streak counts as N=3)
        # The task says "identify streaks of N consecutive down days"
        # Simplest: for each endpoint, record all sub-streaks

        if not is_endpoint:
            continue

        # This is the end of a streak of length `streak_len`
        # Record for each N from 2 to streak_len
        for n in range(2, streak_len + 1):
            # The endpoint for "N consecutive down days" is at position i - (streak_len - n)
            end_idx = i - (streak_len - n)
            if end_idx < 0 or end_idx >= len(daily) - 1:
                continue

            end_date = dates[end_idx]
            end_close = daily["close"].iloc[end_idx]
            end_rsi = daily["rsi"].iloc[end_idx]

            # Next-day return
            if end_idx + 1 < len(daily):
                next_1d_ret = daily["ret"].iloc[end_idx + 1]
            else:
                next_1d_ret = np.nan

            # Max bounce within next 3 days
            max_close_3d = np.nan
            for j in range(1, 4):
                if end_idx + j < len(daily):
                    c = daily["close"].iloc[end_idx + j]
                    if np.isnan(max_close_3d) or c > max_close_3d:
                        max_close_3d = c
            if not np.isnan(max_close_3d):
                max_bounce_3d = (max_close_3d - end_close) / end_close
            else:
                max_bounce_3d = np.nan

            n_label = n if n < 6 else "6+"
            results.append({
                "date": end_date,
                "streak_len": n_label,
                "next_1d_ret": next_1d_ret,
                "max_bounce_3d": max_bounce_3d,
                "rsi": end_rsi,
                "close": end_close,
            })

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def compute_stats(series):
    """Compute mean, median, win rate, N, t-stat, p-value for a return series."""
    s = series.dropna()
    n = len(s)
    if n == 0:
        return {"mean": np.nan, "median": np.nan, "win_rate": np.nan,
                "N": 0, "t_stat": np.nan, "p_value": np.nan}
    mean = s.mean()
    median = s.median()
    win_rate = (s > 0).mean()
    if n >= 2 and s.std() > 0:
        t_stat, p_value = stats.ttest_1samp(s, 0)
    else:
        t_stat, p_value = np.nan, np.nan
    return {"mean": mean, "median": median, "win_rate": win_rate,
            "N": n, "t_stat": t_stat, "p_value": p_value}


def analyze_ticker(ticker, daily, vix_series):
    """Run full analysis for one ticker."""
    print(f"\n{'#'*60}")
    print(f"# Analyzing {ticker}")
    print(f"# Daily bars: {len(daily)}, date range: {daily.index[0].date()} to {daily.index[-1].date()}")
    print(f"{'#'*60}")

    streaks_df = find_streaks(daily)
    if streaks_df.empty:
        print(f"  No streaks found for {ticker}")
        return None

    # Add VIX regime (prior day, no lookahead)
    streaks_df["vix"] = streaks_df["date"].apply(lambda d: get_prior_vix(vix_series, d))
    streaks_df["vix_bucket"] = streaks_df["vix"].apply(classify_vix)
    streaks_df["rsi_bucket"] = streaks_df["rsi"].apply(classify_rsi)

    print(f"  Total streak events: {len(streaks_df)}")
    print(f"  Streak distribution:")
    vc = streaks_df["streak_len"].value_counts()
    # Sort with mixed int/str keys
    order = [k for k in [2, 3, 4, 5, "6+"] if k in vc.index]
    print(vc.reindex(order).to_string())
    print(f"  VIX bucket distribution:")
    print(streaks_df["vix_bucket"].value_counts().to_string())

    return streaks_df


def build_main_table(streaks_df, ticker):
    """Build N_consecutive_days × VIX_bucket table."""
    rows = []
    streak_labels = [2, 3, 4, 5, "6+"]
    vix_labels = [b[2] for b in VIX_BINS]

    for sl in streak_labels:
        for vl in vix_labels:
            mask = (streaks_df["streak_len"] == sl) & (streaks_df["vix_bucket"] == vl)
            subset = streaks_df.loc[mask, "next_1d_ret"]
            st = compute_stats(subset)
            st["streak"] = sl
            st["vix"] = vl
            st["ticker"] = ticker
            rows.append(st)

    return pd.DataFrame(rows)


def build_rsi_table(streaks_df, ticker):
    """Build RSI bucket table for next-day return."""
    rows = []
    rsi_labels = [b[2] for b in RSI_BINS]

    for rl in rsi_labels:
        mask = streaks_df["rsi_bucket"] == rl
        subset = streaks_df.loc[mask, "next_1d_ret"]
        st = compute_stats(subset)
        st["rsi_bucket"] = rl
        st["ticker"] = ticker
        rows.append(st)

    return pd.DataFrame(rows)


def build_bounce3d_table(streaks_df, ticker):
    """Build N_consecutive_days × VIX_bucket table for max 3-day bounce."""
    rows = []
    streak_labels = [2, 3, 4, 5, "6+"]
    vix_labels = [b[2] for b in VIX_BINS]

    for sl in streak_labels:
        for vl in vix_labels:
            mask = (streaks_df["streak_len"] == sl) & (streaks_df["vix_bucket"] == vl)
            subset = streaks_df.loc[mask, "max_bounce_3d"]
            st = compute_stats(subset)
            st["streak"] = sl
            st["vix"] = vl
            st["ticker"] = ticker
            rows.append(st)

    return pd.DataFrame(rows)


def split_sample_validation(streaks_df, ticker):
    """Random 50/50 split, check sign consistency of mean next-day return."""
    idx = np.arange(len(streaks_df))
    np.random.shuffle(idx)
    half = len(idx) // 2
    s1 = streaks_df.iloc[idx[:half]]
    s2 = streaks_df.iloc[idx[half:]]

    results = []
    streak_labels = [2, 3, 4, 5, "6+"]
    for sl in streak_labels:
        m1 = s1.loc[s1["streak_len"] == sl, "next_1d_ret"]
        m2 = s2.loc[s2["streak_len"] == sl, "next_1d_ret"]
        mean1 = m1.mean() if len(m1) > 0 else np.nan
        mean2 = m2.mean() if len(m2) > 0 else np.nan
        consistent = (not np.isnan(mean1)) and (not np.isnan(mean2)) and (np.sign(mean1) == np.sign(mean2))
        results.append({
            "streak": sl, "split1_mean": mean1, "split1_N": len(m1),
            "split2_mean": mean2, "split2_N": len(m2),
            "sign_consistent": consistent, "ticker": ticker,
        })

    return pd.DataFrame(results)


def signal_overlap(btc_streaks, eth_streaks, min_streak=4):
    """When BTC triggers N+ down days, what % of time ETH also triggers same day?"""
    btc_dates = set(btc_streaks.loc[
        btc_streaks["streak_len"].apply(lambda x: (isinstance(x, int) and x >= min_streak) or x == "6+"),
        "date"
    ].apply(lambda d: d.date() if hasattr(d, 'date') else d))

    eth_dates = set(eth_streaks.loc[
        eth_streaks["streak_len"].apply(lambda x: (isinstance(x, int) and x >= min_streak) or x == "6+"),
        "date"
    ].apply(lambda d: d.date() if hasattr(d, 'date') else d))

    if len(btc_dates) == 0:
        return {"btc_triggers": 0, "overlap": 0, "pct": 0}

    overlap = btc_dates & eth_dates
    return {
        "btc_triggers_4plus": len(btc_dates),
        "eth_also_triggers": len(overlap),
        "overlap_pct": len(overlap) / len(btc_dates) * 100 if btc_dates else 0,
        "eth_triggers_4plus": len(eth_dates),
    }


# ---------------------------------------------------------------------------
# Formatting / Output
# ---------------------------------------------------------------------------
def fmt_pct(val, decimals=2):
    if pd.isna(val):
        return "N/A"
    return f"{val*100:.{decimals}f}%"


def fmt_float(val, decimals=2):
    if pd.isna(val):
        return "N/A"
    return f"{val:.{decimals}f}"


def flag_cell(n, p_value, n_cells):
    """Return flags: * for N<10, ** for survives Bonferroni."""
    flags = []
    if n < 10:
        flags.append("†")
    if not np.isnan(p_value) and p_value < 0.05 / n_cells:
        flags.append("*")
    return "".join(flags)


def generate_markdown(results):
    """Generate comprehensive markdown report."""
    lines = []
    lines.append("# Crypto Consecutive Down Days → Bounce Probability Study (Daily)")
    lines.append("")
    lines.append("> **NOTE**: This analysis uses synthetic data generated for pipeline validation.")
    lines.append("> Re-run with real M5 data from Alpha Vantage/Binance for production results.")
    lines.append("")
    lines.append("## Methodology")
    lines.append("- Daily close = last M5 bar of calendar day (crypto 24/7, no session filter)")
    lines.append("- Daily open = first M5 bar of calendar day")
    lines.append("- VIX regime = prior equity trading day close (no lookahead)")
    lines.append("- RSI(14) computed from daily closes")
    lines.append("- Streaks: consecutive calendar days with negative close-to-close return")
    lines.append("- † = N < 10 (low sample size)")
    lines.append("- \\* = survives Bonferroni correction at α = 0.05")
    lines.append("")

    for ticker in TICKERS:
        r = results[ticker]
        lines.append(f"---")
        lines.append(f"## {ticker}USD")
        lines.append(f"")
        lines.append(f"Data range: {r['date_range']}")
        lines.append(f"Total daily bars: {r['n_daily_bars']}")
        lines.append(f"")

        # Main table: Next-day return
        lines.append(f"### Next-Day Return by Streak Length × VIX Regime")
        lines.append("")
        mt = r["main_table"]
        n_cells = len(mt)

        header = "| Streak | VIX | Mean | Median | Win Rate | N | t-stat | p-value | Flags |"
        sep = "|--------|-----|------|--------|----------|---|--------|---------|-------|"
        lines.append(header)
        lines.append(sep)
        for _, row in mt.iterrows():
            fl = flag_cell(row["N"], row["p_value"], n_cells)
            lines.append(
                f"| {row['streak']} | {row['vix']} | {fmt_pct(row['mean'])} | "
                f"{fmt_pct(row['median'])} | {fmt_pct(row['win_rate'])} | "
                f"{int(row['N'])} | {fmt_float(row['t_stat'])} | "
                f"{fmt_float(row['p_value'], 4)} | {fl} |"
            )
        lines.append("")

        # Bounce 3d table
        lines.append(f"### Max 3-Day Bounce by Streak Length × VIX Regime")
        lines.append("")
        bt = r["bounce3d_table"]
        lines.append(header)
        lines.append(sep)
        for _, row in bt.iterrows():
            fl = flag_cell(row["N"], row["p_value"], n_cells)
            lines.append(
                f"| {row['streak']} | {row['vix']} | {fmt_pct(row['mean'])} | "
                f"{fmt_pct(row['median'])} | {fmt_pct(row['win_rate'])} | "
                f"{int(row['N'])} | {fmt_float(row['t_stat'])} | "
                f"{fmt_float(row['p_value'], 4)} | {fl} |"
            )
        lines.append("")

        # RSI table
        lines.append(f"### Next-Day Return by RSI at Streak End")
        lines.append("")
        lines.append("| RSI Bucket | Mean | Median | Win Rate | N | t-stat | p-value |")
        lines.append("|------------|------|--------|----------|---|--------|---------|")
        for _, row in r["rsi_table"].iterrows():
            lines.append(
                f"| {row['rsi_bucket']} | {fmt_pct(row['mean'])} | "
                f"{fmt_pct(row['median'])} | {fmt_pct(row['win_rate'])} | "
                f"{int(row['N'])} | {fmt_float(row['t_stat'])} | "
                f"{fmt_float(row['p_value'], 4)} |"
            )
        lines.append("")

        # Split sample
        lines.append(f"### Split-Sample Validation (50/50 random)")
        lines.append("")
        lines.append("| Streak | Split1 Mean | N1 | Split2 Mean | N2 | Sign Consistent |")
        lines.append("|--------|-------------|-----|-------------|-----|-----------------|")
        for _, row in r["split_sample"].iterrows():
            lines.append(
                f"| {row['streak']} | {fmt_pct(row['split1_mean'])} | "
                f"{int(row['split1_N'])} | {fmt_pct(row['split2_mean'])} | "
                f"{int(row['split2_N'])} | {'Yes' if row['sign_consistent'] else 'No'} |"
            )
        lines.append("")

    # Side-by-side comparison
    lines.append("---")
    lines.append("## BTC vs ETH Side-by-Side (Key Cells)")
    lines.append("")
    lines.append("| Streak | VIX | BTC Mean | BTC WR | BTC N | ETH Mean | ETH WR | ETH N |")
    lines.append("|--------|-----|----------|--------|-------|----------|--------|-------|")

    btc_mt = results["BTC"]["main_table"]
    eth_mt = results["ETH"]["main_table"]
    for sl in [2, 3, 4, 5, "6+"]:
        for vl in ["<16", "16-20", "20-25", ">=25"]:
            b = btc_mt[(btc_mt["streak"] == sl) & (btc_mt["vix"] == vl)]
            e = eth_mt[(eth_mt["streak"] == sl) & (eth_mt["vix"] == vl)]
            if len(b) == 0 or len(e) == 0:
                continue
            b = b.iloc[0]
            e = e.iloc[0]
            if b["N"] == 0 and e["N"] == 0:
                continue
            lines.append(
                f"| {sl} | {vl} | {fmt_pct(b['mean'])} | {fmt_pct(b['win_rate'])} | "
                f"{int(b['N'])} | {fmt_pct(e['mean'])} | {fmt_pct(e['win_rate'])} | "
                f"{int(e['N'])} |"
            )
    lines.append("")

    # Signal overlap
    lines.append("## Signal Overlap")
    lines.append("")
    ol = results["overlap"]
    lines.append(f"- BTC 4+ down day triggers: **{ol['btc_triggers_4plus']}**")
    lines.append(f"- ETH also triggers same day: **{ol['eth_also_triggers']}** ({ol['overlap_pct']:.1f}%)")
    lines.append(f"- ETH 4+ down day triggers: **{ol['eth_triggers_4plus']}**")
    lines.append("")

    # Equity comparison
    lines.append("## Comparison to Equity Benchmark")
    lines.append("")
    lines.append("| Metric | Equity (4 down + VIX≥25) | BTC (4 down + VIX≥25) | ETH (4 down + VIX≥25) |")
    lines.append("|--------|--------------------------|------------------------|-----------------------|")

    btc_key = btc_mt[(btc_mt["streak"] == 4) & (btc_mt["vix"] == ">=25")]
    eth_key = eth_mt[(eth_mt["streak"] == 4) & (eth_mt["vix"] == ">=25")]
    eq_mean, eq_wr, eq_n = "+5.52%", "73%", "22"

    if len(btc_key) > 0 and len(eth_key) > 0:
        bk, ek = btc_key.iloc[0], eth_key.iloc[0]
        lines.append(f"| Mean next-day | {eq_mean} | {fmt_pct(bk['mean'])} | {fmt_pct(ek['mean'])} |")
        lines.append(f"| Win rate | {eq_wr} | {fmt_pct(bk['win_rate'])} | {fmt_pct(ek['win_rate'])} |")
        lines.append(f"| N | {eq_n} | {int(bk['N'])} | {int(ek['N'])} |")
    else:
        lines.append(f"| Mean next-day | {eq_mean} | N/A | N/A |")
        lines.append(f"| Win rate | {eq_wr} | N/A | N/A |")
        lines.append(f"| N | {eq_n} | N/A | N/A |")

    lines.append("")
    lines.append("---")
    lines.append(f"*Generated by crypto_bounce_daily.py*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("Loading data...")
    vix_series = load_vix()

    all_results = {}
    all_streaks = {}

    for ticker in TICKERS:
        daily = load_m5(ticker)
        streaks_df = analyze_ticker(ticker, daily, vix_series)

        if streaks_df is None or streaks_df.empty:
            print(f"No streak data for {ticker}, skipping.")
            continue

        main_table = build_main_table(streaks_df, ticker)
        bounce3d_table = build_bounce3d_table(streaks_df, ticker)
        rsi_table = build_rsi_table(streaks_df, ticker)
        split_val = split_sample_validation(streaks_df, ticker)

        all_results[ticker] = {
            "main_table": main_table,
            "bounce3d_table": bounce3d_table,
            "rsi_table": rsi_table,
            "split_sample": split_val,
            "date_range": f"{daily.index[0].date()} to {daily.index[-1].date()}",
            "n_daily_bars": len(daily),
        }
        all_streaks[ticker] = streaks_df

        # Save per-ticker CSV
        streaks_df.to_csv(os.path.join(OUTPUT_DIR, f"{ticker}_streaks.csv"), index=False)
        main_table.to_csv(os.path.join(OUTPUT_DIR, f"{ticker}_main_table.csv"), index=False)
        rsi_table.to_csv(os.path.join(OUTPUT_DIR, f"{ticker}_rsi_table.csv"), index=False)

    if len(all_results) < 2:
        print("ERROR: Need both BTC and ETH results for comparison.")
        sys.exit(1)

    # Signal overlap
    all_results["overlap"] = signal_overlap(all_streaks["BTC"], all_streaks["ETH"])

    # Generate markdown
    md = generate_markdown(all_results)
    md_path = os.path.join(OUTPUT_DIR, "CRYPTO_BOUNCE_DAILY_RESULTS.md")
    with open(md_path, "w") as f:
        f.write(md)
    print(f"\nResults saved to {md_path}")

    # Also save to repo root as specified
    root_md = "CRYPTO_BOUNCE_DAILY_RESULTS.md"
    with open(root_md, "w") as f:
        f.write(md)
    print(f"Results also saved to {root_md}")

    # Print key findings
    print("\n" + "=" * 60)
    print("KEY FINDINGS SUMMARY")
    print("=" * 60)
    for ticker in TICKERS:
        r = all_results[ticker]
        mt = r["main_table"]
        key = mt[(mt["streak"] == 4) & (mt["vix"] == ">=25")]
        if len(key) > 0:
            k = key.iloc[0]
            print(f"{ticker}: 4 down days + VIX>=25 → mean={fmt_pct(k['mean'])}, "
                  f"WR={fmt_pct(k['win_rate'])}, N={int(k['N'])}")
        else:
            print(f"{ticker}: 4 down days + VIX>=25 → no data")

    ol = all_results["overlap"]
    print(f"\nSignal overlap (4+ down days): {ol['overlap_pct']:.1f}%")


if __name__ == "__main__":
    main()
