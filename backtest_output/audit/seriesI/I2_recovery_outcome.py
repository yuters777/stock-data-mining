"""
Series I2: Recovery Outcome Analysis — continuation vs reversal.

For each day with DZ compression >= 0.3%:
1. recovery_return = (close_15:55 - DZ_low) / DZ_low * 100
2. Classify:
   - full_recovery: close > Z2_high
   - partial_recovery: close > DZ_low + 0.5*(Z2_high - DZ_low)
   - failed_recovery: close < DZ_low + 0.25*(Z2_high - DZ_low)
   - weak_recovery: everything else
3. Stats by VIX regime, compression severity, event day
"""

import sys
from pathlib import Path
from datetime import timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── paths ──
ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "Fetched_Data"
OUT_DIR = Path(__file__).resolve().parent
VIX_PATH = DATA_DIR / "VIXCLS_FRED_real.csv"

EQUITY_TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "SPY", "TSLA", "TSM", "TXN", "V",
]

# IST zone boundaries
Z2_START = 17 * 60
Z2_END = 19 * 60
Z3_START = 19 * 60
Z3_END = 20 * 60 + 30

MIN_COMPRESSION_PCT = 0.3


def ist_minutes(dt):
    return dt.hour * 60 + dt.minute


def load_vix():
    vix = pd.read_csv(VIX_PATH)
    vix.columns = ["date", "vix"]
    vix["date"] = pd.to_datetime(vix["date"]).dt.date
    vix["vix"] = pd.to_numeric(vix["vix"], errors="coerce")
    vix = vix.dropna(subset=["vix"])
    return vix.set_index("date")["vix"].to_dict()


def vix_regime(vix_val):
    if vix_val is None or np.isnan(vix_val):
        return "unknown"
    if vix_val < 20:
        return "<20"
    elif vix_val < 25:
        return "20-25"
    return ">=25"


def compression_bucket(pct):
    if pct < 0.5:
        return "<0.5%"
    elif pct < 1.0:
        return "0.5-1.0%"
    return ">1.0%"


def load_regular_session(ticker):
    path = DATA_DIR / f"{ticker}_data.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["Datetime"])
    df = df.sort_values("Datetime").reset_index(drop=True)
    mins = df["Datetime"].apply(ist_minutes)
    # Regular session excluding first bar (16:30) but including close-area bars
    # We need up to 22:55 IST = 15:55 ET for EOD close
    mask = (mins >= 16 * 60 + 35) & (mins <= 22 * 60 + 55)
    df = df[mask].copy()
    df["trading_day"] = df["Datetime"].dt.date
    return df


def analyze_ticker(ticker, vix_map):
    df = load_regular_session(ticker)
    if df is None or df.empty:
        return []

    # Build VIX daily change for event detection
    vix_dates = sorted(vix_map.keys())
    vix_daily_change = {}
    for i in range(1, len(vix_dates)):
        prev_vix = vix_map[vix_dates[i - 1]]
        curr_vix = vix_map[vix_dates[i]]
        if prev_vix > 0:
            vix_daily_change[vix_dates[i]] = abs(curr_vix - prev_vix) / prev_vix * 100

    results = []
    for day, day_df in df.groupby("trading_day"):
        mins = day_df["Datetime"].apply(ist_minutes)

        z2 = day_df[(mins >= Z2_START) & (mins < Z2_END)]
        z3 = day_df[(mins >= Z3_START) & (mins < Z3_END)]
        if z2.empty or z3.empty:
            continue

        z2_high = z2["High"].max()
        dz_low = z3["Low"].min()

        if z2_high <= 0:
            continue
        compression_pct = (z2_high - dz_low) / z2_high * 100
        if compression_pct < MIN_COMPRESSION_PCT:
            continue

        # EOD close = last bar's close (22:55 IST = 15:55 ET)
        eod_close = day_df.iloc[-1]["Close"]

        # Recovery return
        recovery_return = (eod_close - dz_low) / dz_low * 100

        # Classification
        full_threshold = z2_high
        partial_threshold = dz_low + 0.5 * (z2_high - dz_low)
        failed_threshold = dz_low + 0.25 * (z2_high - dz_low)

        if eod_close > full_threshold:
            category = "full_recovery"
        elif eod_close > partial_threshold:
            category = "partial_recovery"
        elif eod_close < failed_threshold:
            category = "failed_recovery"
        else:
            category = "weak_recovery"

        vix_val = vix_map.get(day)
        regime = vix_regime(vix_val)
        comp_bucket = compression_bucket(compression_pct)

        # Event day detection: VIX daily change > 2%
        vix_chg = vix_daily_change.get(day, 0)
        is_event = vix_chg > 2

        results.append({
            "ticker": ticker,
            "trading_day": day,
            "z2_high": z2_high,
            "dz_low": dz_low,
            "eod_close": eod_close,
            "compression_pct": compression_pct,
            "recovery_return_pct": recovery_return,
            "category": category,
            "vix": vix_val,
            "vix_regime": regime,
            "compression_bucket": comp_bucket,
            "is_event_day": is_event,
            "vix_daily_change_pct": vix_chg,
        })

    return results


def print_category_table(df, group_col, group_name):
    """Print category distribution by a grouping column."""
    print(f"\n--- Recovery Outcome by {group_name} ---")
    cats = ["full_recovery", "partial_recovery", "weak_recovery", "failed_recovery"]
    groups = sorted(df[group_col].unique())

    header = f"{'':>12s}"
    for c in cats:
        header += f"  {c:>16s}"
    header += f"  {'N':>6s}"
    print(header)

    for g in groups:
        sub = df[df[group_col] == g]
        n = len(sub)
        row = f"{str(g):>12s}"
        for c in cats:
            cnt = (sub["category"] == c).sum()
            pct = cnt / n * 100 if n > 0 else 0
            row += f"  {pct:>14.1f}%"
        row += f"  {n:>6d}"
        print(row)

    # Overall
    n = len(df)
    row = f"{'ALL':>12s}"
    for c in cats:
        cnt = (df["category"] == c).sum()
        pct = cnt / n * 100 if n > 0 else 0
        row += f"  {pct:>14.1f}%"
    row += f"  {n:>6d}"
    print(row)


def main():
    print("Loading VIX data...")
    vix_map = load_vix()

    all_results = []
    for ticker in EQUITY_TICKERS:
        results = analyze_ticker(ticker, vix_map)
        all_results.extend(results)
        if results:
            print(f"  {ticker}: {len(results)} DZ compression days")

    df = pd.DataFrame(all_results)
    df.to_csv(OUT_DIR / "I2_recovery_outcome_data.csv", index=False)

    print(f"\n{'='*60}")
    print(f"I2: Recovery Outcome Analysis")
    print(f"{'='*60}")
    print(f"Total ticker-days with DZ compression >= {MIN_COMPRESSION_PCT}%: {len(df)}")

    # Category distribution
    for cat in ["full_recovery", "partial_recovery", "weak_recovery", "failed_recovery"]:
        cnt = (df["category"] == cat).sum()
        print(f"  {cat:>20s}: {cnt:5d} ({cnt/len(df)*100:.1f}%)")

    # By VIX regime
    print_category_table(df, "vix_regime", "VIX Regime")

    # By compression severity
    print_category_table(df, "compression_bucket", "Compression Severity")

    # By event day
    print_category_table(df, "is_event_day", "Event Day (VIX chg > 2%)")

    # ── Plots ──
    # 1. Scatter: DZ compression vs EOD recovery return
    fig, ax = plt.subplots(figsize=(10, 6))
    colors_map = {
        "full_recovery": "#4CAF50",
        "partial_recovery": "#2196F3",
        "weak_recovery": "#FF9800",
        "failed_recovery": "#F44336",
    }
    for cat, color in colors_map.items():
        sub = df[df["category"] == cat]
        ax.scatter(
            sub["compression_pct"], sub["recovery_return_pct"],
            c=color, label=cat, alpha=0.4, s=15, edgecolors="none"
        )
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="-")
    ax.set_xlabel("DZ Compression (%)")
    ax.set_ylabel("EOD Recovery Return (%)")
    ax.set_title(f"I2: DZ Compression vs EOD Recovery (N={len(df)})")
    ax.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "I2_compression_vs_recovery_scatter.png", dpi=150)
    plt.close()
    print(f"\nSaved: I2_compression_vs_recovery_scatter.png")

    # 2. Stacked bar chart by VIX regime
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    cats = ["full_recovery", "partial_recovery", "weak_recovery", "failed_recovery"]
    cat_colors = ["#4CAF50", "#2196F3", "#FF9800", "#F44336"]

    for idx, (group_col, title) in enumerate([
        ("vix_regime", "VIX Regime"),
        ("compression_bucket", "Compression Severity"),
        ("is_event_day", "Event Day"),
    ]):
        ax = axes[idx]
        groups = sorted(df[group_col].unique())
        bottoms = np.zeros(len(groups))
        for cat, color in zip(cats, cat_colors):
            vals = []
            for g in groups:
                sub = df[df[group_col] == g]
                n = len(sub)
                vals.append((sub["category"] == cat).sum() / n * 100 if n > 0 else 0)
            ax.bar(range(len(groups)), vals, bottom=bottoms, color=color,
                   label=cat, alpha=0.85, edgecolor="white")
            bottoms += vals
        ax.set_xticks(range(len(groups)))
        ax.set_xticklabels([str(g) for g in groups], fontsize=9)
        ax.set_ylabel("% of days")
        ax.set_title(title)
        if idx == 2:
            ax.legend(fontsize=7, loc="upper right")

    plt.suptitle("I2: Recovery Outcome Distribution", fontsize=13)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "I2_outcome_by_regime.png", dpi=150)
    plt.close()
    print("Saved: I2_outcome_by_regime.png")


if __name__ == "__main__":
    main()
