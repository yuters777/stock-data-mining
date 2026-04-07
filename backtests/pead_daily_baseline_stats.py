"""
PEAD Daily Baseline — Stats + Parameter Sweep (Part 1b of 3).

Reads results/pead_events_daily.csv (from part 1a) and produces:
  1. Baseline statistics (no filtering)
  2. Stratified analysis (EPS surprise, VIX, first-bar, direction×surprise)
  3. Parameter sweep for Module 5 candidate config
  4. Random baseline comparison (bootstrap)

Produces:
  - Console output with all tables
  - results/pead_daily_baseline.md (markdown summary)

Usage:
    python backtests/pead_daily_baseline_stats.py
"""

import sys
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from tabulate import tabulate

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

INPUT_CSV = _REPO_ROOT / "results" / "pead_events_daily.csv"
OUTPUT_MD = _REPO_ROOT / "results" / "pead_daily_baseline.md"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pf(returns: pd.Series) -> float:
    """Profit factor: sum(wins) / abs(sum(losses))."""
    wins = returns[returns > 0].sum()
    losses = returns[returns < 0].sum()
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / abs(losses)


def wr(returns: pd.Series) -> float:
    """Win rate as percentage."""
    if len(returns) == 0:
        return 0.0
    return (returns > 0).sum() / len(returns) * 100


def pval(returns: pd.Series) -> float:
    """Two-sided t-test p-value against mean=0."""
    if len(returns) < 2:
        return np.nan
    _, p = scipy_stats.ttest_1samp(returns.dropna(), 0)
    return p


def fmt_pf(v):
    return "inf" if np.isinf(v) else f"{v:.2f}"


def fmt_p(v):
    if pd.isna(v):
        return "—"
    if v < 0.001:
        return "<.001"
    if v < 0.01:
        return f"{v:.3f}"
    return f"{v:.2f}"


# ---------------------------------------------------------------------------
# Section 1: Baseline Statistics
# ---------------------------------------------------------------------------
def section1_baseline(df, out):
    out.write("# PEAD Daily Baseline Statistics\n\n")
    out.write("## Section 1: Baseline (no filters)\n\n")

    # 1a. Overall drift
    out.write("### 1a. Overall drift\n\n")
    rows = []
    for d in ["drift_1d", "drift_3d", "drift_5d", "drift_10d"]:
        s = df[d].dropna()
        rows.append([
            d, len(s), f"{s.mean():.3f}", f"{s.median():.3f}",
            f"{wr(s):.1f}", fmt_p(pval(s)),
        ])
    tbl = tabulate(rows, headers=["metric", "N", "mean%", "median%", "WR%", "p-val"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")

    # 1b. By direction
    out.write("### 1b. By direction\n\n")
    rows = []
    for label, mask in [("GAP UP", df["gap_pct"] > 0), ("GAP DOWN", df["gap_pct"] < 0)]:
        sub = df[mask]
        for d in ["drift_1d", "drift_3d", "drift_5d"]:
            s = sub[d].dropna()
            rows.append([
                label, d, len(s), f"{s.mean():.3f}", f"{wr(s):.1f}",
                fmt_pf(pf(s)), fmt_p(pval(s)),
            ])
    tbl = tabulate(rows, headers=["dir", "metric", "N", "mean%", "WR%", "PF", "p-val"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")

    # 1c. Gap size distribution
    out.write("### 1c. Gap size distribution\n\n")
    abs_gap = df["gap_pct"].abs()
    buckets = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 100)]
    rows = []
    for lo, hi in buckets:
        mask = (abs_gap >= lo) & (abs_gap < hi)
        sub = df[mask]
        s5 = sub["drift_5d"].dropna()
        label = f"{lo}-{hi}%" if hi < 100 else f">{lo}%"
        rows.append([
            label, len(sub), f"{sub['gap_pct'].abs().mean():.2f}" if len(sub) else "—",
            f"{s5.mean():.3f}" if len(s5) else "—",
            f"{wr(s5):.1f}" if len(s5) else "—",
        ])
    tbl = tabulate(rows, headers=["bucket", "N", "mean|gap|%", "mean_drift5d%", "WR5d%"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")

    # 1d. Continuation rate
    valid = df[(df["gap_pct"] != 0) & df["drift_5d"].notna()].copy()
    cont = (np.sign(valid["drift_5d"]) == np.sign(valid["gap_pct"])).sum()
    rate = cont / len(valid) * 100 if len(valid) else 0
    out.write(f"### 1d. Continuation rate\n\n")
    out.write(f"Events where sign(drift_5d) == sign(gap_pct): **{cont}/{len(valid)} ({rate:.1f}%)**\n\n")


# ---------------------------------------------------------------------------
# Section 2: Stratified Analysis
# ---------------------------------------------------------------------------
def _strat_table(sub, label):
    """Return a row of stats for a subset."""
    rows = []
    for d in ["drift_1d", "drift_3d", "drift_5d"]:
        s = sub[d].dropna()
        rows.append([
            label, d, len(s), f"{s.mean():.3f}",
            f"{wr(s):.1f}", fmt_pf(pf(s)),
        ])
    return rows


def section2_stratified(df, out):
    out.write("## Section 2: Stratified Analysis\n\n")

    # 2a. EPS surprise buckets
    out.write("### 2a. By EPS surprise\n\n")
    rows = []
    has_eps = df["eps_surprise_pct"].notna()
    buckets = [
        ("Big beat (>10%)", has_eps & (df["eps_surprise_pct"] > 10)),
        ("Small beat (0-10%)", has_eps & (df["eps_surprise_pct"] >= 0) & (df["eps_surprise_pct"] <= 10)),
        ("Miss (<0%)", has_eps & (df["eps_surprise_pct"] < 0)),
        ("No data", ~has_eps),
    ]
    for label, mask in buckets:
        rows.extend(_strat_table(df[mask], label))
    tbl = tabulate(rows, headers=["group", "metric", "N", "mean%", "WR%", "PF"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")

    # 2b. VIX regime
    out.write("### 2b. By VIX regime\n\n")
    rows = []
    has_vix = df["vix_on_day"].notna()
    vix_buckets = [
        ("Low (<20)", has_vix & (df["vix_on_day"] < 20)),
        ("Medium (20-25)", has_vix & (df["vix_on_day"] >= 20) & (df["vix_on_day"] < 25)),
        ("High (>=25)", has_vix & (df["vix_on_day"] >= 25)),
    ]
    for label, mask in vix_buckets:
        sub = df[mask]
        for d in ["drift_1d", "drift_5d"]:
            s = sub[d].dropna()
            rows.append([label, d, len(s), f"{s.mean():.3f}", f"{wr(s):.1f}"])
    tbl = tabulate(rows, headers=["VIX", "metric", "N", "mean%", "WR%"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")

    # 2c. First bar holds
    out.write("### 2c. By first_bar_holds\n\n")
    rows = []
    for label, val in [("Holds", True), ("Doesn't hold", False)]:
        rows.extend(_strat_table(df[df["first_bar_holds"] == val], label))
    tbl = tabulate(rows, headers=["bar", "metric", "N", "mean%", "WR%", "PF"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")

    # 2d. First bar strong
    out.write("### 2d. By first_bar_strong\n\n")
    rows = []
    for label, val in [("Strong", True), ("Weak", False)]:
        rows.extend(_strat_table(df[df["first_bar_strong"] == val], label))
    tbl = tabulate(rows, headers=["bar", "metric", "N", "mean%", "WR%", "PF"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")

    # 2e. Direction × surprise
    out.write("### 2e. Direction × Surprise (Module 5 candidates)\n\n")
    rows = []
    combos = [
        ("GAP UP + big beat",
         (df["gap_pct"] > 0) & (df["eps_surprise_pct"] > 10)),
        ("GAP UP + small beat",
         (df["gap_pct"] > 0) & (df["eps_surprise_pct"] >= 0) & (df["eps_surprise_pct"] <= 10)),
        ("GAP DOWN + miss",
         (df["gap_pct"] < 0) & (df["eps_surprise_pct"] < 0)),
    ]
    for label, mask in combos:
        rows.extend(_strat_table(df[mask], label))
    tbl = tabulate(rows, headers=["combo", "metric", "N", "mean%", "WR%", "PF"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")


# ---------------------------------------------------------------------------
# Section 3: Parameter Sweep
# ---------------------------------------------------------------------------
def section3_sweep(df, out):
    out.write("## Section 3: Parameter Sweep\n\n")

    gap_thresholds = [1.0, 2.0, 3.0, 4.0, 5.0]
    hold_periods = [1, 2, 3, 5, 10]
    surprise_filters = [0, 5, 10, 15, 20]
    directions = ["LONG_ONLY", "SHORT_ONLY", "BOTH"]
    first_bar_filters = [False, True]

    results = []

    for gap_thr in gap_thresholds:
        for hold_d in hold_periods:
            for surp_thr in surprise_filters:
                for direction in directions:
                    for fb in first_bar_filters:
                        # Build filter
                        mask = df["gap_pct"].abs() >= gap_thr

                        if direction == "LONG_ONLY":
                            mask &= df["gap_pct"] > 0
                        elif direction == "SHORT_ONLY":
                            mask &= df["gap_pct"] < 0

                        if surp_thr > 0:
                            mask &= df["eps_surprise_pct"].abs() >= surp_thr

                        if fb:
                            mask &= df["first_bar_holds"]

                        sub = df[mask]
                        drift_col = f"drift_{hold_d}d"
                        returns = sub[drift_col].dropna()

                        # For SHORT_ONLY, negate returns (short profits from drops)
                        if direction == "SHORT_ONLY":
                            returns = -returns

                        n = len(returns)
                        if n < 20:
                            continue

                        results.append({
                            "gap_thr": gap_thr,
                            "hold_d": hold_d,
                            "surprise_thr": surp_thr,
                            "direction": direction,
                            "first_bar": fb,
                            "N": n,
                            "mean%": returns.mean(),
                            "WR%": wr(returns),
                            "PF": pf(returns),
                            "p_value": pval(returns),
                        })

    res_df = pd.DataFrame(results)
    if res_df.empty:
        out.write("No configurations met N >= 20.\n\n")
        return res_df

    res_df.sort_values("PF", ascending=False, inplace=True)
    res_df.reset_index(drop=True, inplace=True)

    # Format table
    rows = []
    for _, r in res_df.iterrows():
        rows.append([
            r["gap_thr"], r["hold_d"], r["surprise_thr"], r["direction"],
            r["first_bar"], r["N"],
            f"{r['mean%']:.3f}", f"{r['WR%']:.1f}",
            fmt_pf(r["PF"]), fmt_p(r["p_value"]),
        ])

    tbl = tabulate(rows,
                   headers=["gap_thr", "hold_d", "surp_thr", "direction",
                            "first_bar", "N", "mean%", "WR%", "PF", "p-val"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")

    # Highlight Module 5 candidate
    m5 = res_df[
        (res_df["direction"] == "LONG_ONLY") &
        (res_df["gap_thr"] >= 2.0) &
        (res_df["surprise_thr"] >= 10) &
        (res_df["first_bar"] == True)
    ]
    if not m5.empty:
        out.write("### Module 5 Candidate (LONG + gap>=2% + surprise>=10% + first_bar_holds)\n\n")
        rows = []
        for _, r in m5.iterrows():
            rows.append([
                r["gap_thr"], r["hold_d"], r["surprise_thr"], r["N"],
                f"{r['mean%']:.3f}", f"{r['WR%']:.1f}",
                fmt_pf(r["PF"]), fmt_p(r["p_value"]),
            ])
        tbl = tabulate(rows,
                       headers=["gap_thr", "hold_d", "surp_thr", "N",
                                "mean%", "WR%", "PF", "p-val"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")
    else:
        out.write("### Module 5 Candidate\n\nNo configs with N >= 20 met the Module 5 filter.\n\n")

    return res_df


# ---------------------------------------------------------------------------
# Section 4: Random Baseline (Bootstrap)
# ---------------------------------------------------------------------------
def section4_bootstrap(df, sweep_df, out):
    out.write("## Section 4: Random Baseline (Bootstrap)\n\n")

    if sweep_df is None or sweep_df.empty:
        out.write("No sweep results to bootstrap against.\n\n")
        return

    # Top 3 by PF with N >= 30
    top = sweep_df[sweep_df["N"] >= 30].head(3)
    if top.empty:
        out.write("No configs with N >= 30 for bootstrap.\n\n")
        return

    rng = np.random.RandomState(42)
    n_boot = 10_000

    # We need a pool of all daily returns for random sampling
    # Use all tickers' price data to build a pool of N-day returns
    # For simplicity: use drift columns directly from all events as our pool
    # (conservative: events are a subset of all trading days)
    # Better: compute from the raw daily data - but we only have the events CSV
    # So we use the full event set as the sampling pool

    rows = []
    for idx, config in top.iterrows():
        hold_d = int(config["hold_d"])
        drift_col = f"drift_{hold_d}d"
        n_events = int(config["N"])
        actual_mean = config["mean%"]
        direction = config["direction"]

        # Pool: all available drift values for this hold period
        pool = df[drift_col].dropna().values
        if direction == "SHORT_ONLY":
            pool = -pool

        # Bootstrap
        boot_means = []
        for _ in range(n_boot):
            sample = rng.choice(pool, size=n_events, replace=True)
            boot_means.append(sample.mean())

        boot_means = np.array(boot_means)
        pctile = (boot_means < actual_mean).sum() / n_boot * 100
        boot_p = 2 * min(pctile, 100 - pctile) / 100  # two-sided

        rows.append([
            f"g>={config['gap_thr']} {config['direction']} surp>={config['surprise_thr']} "
            f"fb={config['first_bar']} hold={hold_d}d",
            n_events, f"{actual_mean:.3f}",
            f"{np.mean(boot_means):.3f}", f"{np.std(boot_means):.3f}",
            f"{pctile:.1f}", f"{boot_p:.3f}",
        ])

    tbl = tabulate(rows,
                   headers=["config", "N", "actual_mean%", "rand_mean%",
                            "rand_std%", "percentile", "boot_p"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")
    out.write("*Bootstrap: 10,000 iterations sampling from all events pool, seed=42.*\n\n")


# ---------------------------------------------------------------------------
# Section 5: Verdict
# ---------------------------------------------------------------------------
def section5_verdict(sweep_df, out):
    out.write("## Verdict\n\n")

    if sweep_df is None or sweep_df.empty:
        out.write("No sweep results to evaluate.\n\n")
        return

    # Pass criteria: N >= 30, PF >= 1.5, WR >= 55%
    passing = sweep_df[
        (sweep_df["N"] >= 30) &
        (sweep_df["PF"] >= 1.5) &
        (sweep_df["WR%"] >= 55)
    ].copy()

    if passing.empty:
        out.write("**No configurations pass all criteria (N>=30, PF>=1.5, WR>=55%).**\n\n")
    else:
        out.write(f"**{len(passing)} configuration(s) pass all criteria (N>=30, PF>=1.5, WR>=55%):**\n\n")
        rows = []
        for _, r in passing.iterrows():
            rows.append([
                r["gap_thr"], r["hold_d"], r["surprise_thr"], r["direction"],
                r["first_bar"], r["N"],
                f"{r['mean%']:.3f}", f"{r['WR%']:.1f}",
                fmt_pf(r["PF"]), fmt_p(r["p_value"]),
            ])
        tbl = tabulate(rows,
                       headers=["gap_thr", "hold_d", "surp_thr", "direction",
                                "first_bar", "N", "mean%", "WR%", "PF", "p-val"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")

    # Module 5 candidate assessment
    out.write("### Module 5 Candidate Assessment\n\n")
    m5 = sweep_df[
        (sweep_df["direction"] == "LONG_ONLY") &
        (sweep_df["gap_thr"] >= 2.0) &
        (sweep_df["surprise_thr"] >= 10) &
        (sweep_df["first_bar"] == True)
    ]
    if m5.empty:
        out.write("No Module 5 candidate configs met N >= 20. "
                  "Likely insufficient EPS surprise data to filter this aggressively.\n\n")
    else:
        best = m5.iloc[0]
        verdict = "PASS" if best["N"] >= 30 and best["PF"] >= 1.5 and best["WR%"] >= 55 else "PROVISIONAL"
        out.write(f"Best Module 5 config: gap>={best['gap_thr']}% + surprise>={best['surprise_thr']}% "
                  f"+ first_bar_holds, hold={int(best['hold_d'])}d\n")
        out.write(f"N={int(best['N'])}, mean={best['mean%']:.3f}%, WR={best['WR%']:.1f}%, "
                  f"PF={fmt_pf(best['PF'])}, p={fmt_p(best['p_value'])}\n")
        out.write(f"**Status: {verdict}**\n\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    df = pd.read_csv(INPUT_CSV)
    print(f"Loaded {len(df)} events from {INPUT_CSV.name}")
    print(f"Tickers: {df['ticker'].nunique()}, Date range: {df['event_day'].min()} – {df['event_day'].max()}")
    print()

    md = StringIO()

    # Section 1
    section1_baseline(df, md)
    # Section 2
    section2_stratified(df, md)
    # Section 3
    sweep_df = section3_sweep(df, md)
    # Section 4
    section4_bootstrap(df, sweep_df, md)
    # Section 5
    section5_verdict(sweep_df, md)

    # Print to console
    content = md.getvalue()
    print(content)

    # Save markdown
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(content)
    print(f"\nSaved → {OUTPUT_MD}")


if __name__ == "__main__":
    main()
