#!/usr/bin/env python3
"""
Stress MR v2 — Part 1: Does ANY Intraday MR Signal Exist?

Exploration of laggard-leader mean reversion on stress days across
ALL entry×exit time combinations using FIXED regular-session M5 data.

Output: PART1_HEAT_MAP_RESULTS.md
"""

import json
import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# ── Configuration ──────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent  # backtest_output/
OUTPUT_DIR = Path(__file__).parent       # backtest_output/stress_mr_v2/

ALL_TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN", "COST",
    "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU", "NVDA",
    "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

STRESS_THRESHOLD = -0.75  # percent

ENTRY_TIMES = [dtime(10, 0), dtime(10, 30), dtime(11, 0), dtime(11, 30), dtime(12, 0)]
EXIT_TIMES_RELATIVE = [60, 120, 180]  # minutes forward
EXIT_TIMES_FIXED = [dtime(15, 0), dtime(15, 30), dtime(15, 55)]

MEASUREMENT_TIMES = [dtime(10, 30), dtime(11, 0), dtime(11, 30), dtime(12, 0)]

QUINTILE_SIZE = 5  # bottom 5 / top 5

# ── Data Loading ───────────────────────────────────────────────────────────

def load_all_m5():
    """Load M5 regular-session data for all 25 equity tickers + SPY."""
    frames = {}
    for ticker in ALL_TICKERS + ["SPY"]:
        fp = DATA_DIR / f"{ticker}_m5_regsess.csv"
        if not fp.exists():
            print(f"WARNING: {fp} not found, skipping {ticker}")
            continue
        df = pd.read_csv(fp, parse_dates=["Datetime"])
        df["date"] = df["Datetime"].dt.date
        df["time"] = df["Datetime"].dt.time
        frames[ticker] = df
    print(f"Loaded {len(frames)} tickers, "
          f"date range: {frames['SPY']['date'].min()} → {frames['SPY']['date'].max()}")
    return frames


def build_return_matrix(frames):
    """Build a (date × time × ticker) return-from-open matrix.

    Returns dict: {ticker: DataFrame with index=date, columns=time, values=return%}
    """
    open_prices = {}  # {ticker: {date: open_price_at_0930}}
    return_matrices = {}

    for ticker in ALL_TICKERS + ["SPY"]:
        if ticker not in frames:
            continue
        df = frames[ticker]
        # Get 09:30 open for each day
        opens = df[df["time"] == dtime(9, 30)].set_index("date")["Open"]
        open_prices[ticker] = opens

        # Pivot: rows=date, cols=time, values=Close
        pivot = df.pivot_table(index="date", columns="time", values="Close")
        # Return from open (%)
        ret = pivot.div(opens, axis=0).subtract(1).multiply(100)
        return_matrices[ticker] = ret

    return return_matrices, open_prices


# ── Task 1: Stress Day Identification ─────────────────────────────────────

def identify_stress_days(return_matrices):
    """Compute median return across 25 tickers at various measurement times.
    Returns stress day classifications at each measurement time.
    """
    results = {}
    trading_dates = sorted(return_matrices[ALL_TICKERS[0]].index)

    for mtime in MEASUREMENT_TIMES:
        median_returns = []
        for d in trading_dates:
            rets = []
            for ticker in ALL_TICKERS:
                rm = return_matrices[ticker]
                if d in rm.index and mtime in rm.columns:
                    val = rm.loc[d, mtime]
                    if pd.notna(val):
                        rets.append(val)
            if len(rets) >= 15:  # need enough tickers
                median_returns.append((d, np.median(rets)))
            else:
                median_returns.append((d, np.nan))

        df = pd.DataFrame(median_returns, columns=["date", "median_return"])
        df["is_stress"] = df["median_return"] < STRESS_THRESHOLD
        results[mtime] = df

    return results


def get_spy_daily_returns(return_matrices):
    """Get SPY return at 15:55 (close) for each day."""
    spy = return_matrices.get("SPY")
    if spy is None:
        return {}
    close_time = dtime(15, 55)
    if close_time in spy.columns:
        return spy[close_time].to_dict()
    return {}


# ── Task 2 & 3: Laggard-Leader Analysis ───────────────────────────────────

def compute_heat_map(return_matrices, stress_dates, frames):
    """Compute laggard-leader spread for all entry×exit combinations.

    Args:
        return_matrices: {ticker: DataFrame(date×time → return%)}
        stress_dates: set of dates to include
        frames: raw M5 frames (for price lookups)

    Returns:
        Dict of results keyed by (entry_time, exit_label)
    """
    results = {}
    trading_dates = sorted(stress_dates)
    n_days = len(trading_dates)

    if n_days == 0:
        return results

    for entry_time in ENTRY_TIMES:
        # For each day, rank tickers by return at entry_time
        day_rankings = {}
        for d in trading_dates:
            rets = {}
            for ticker in ALL_TICKERS:
                rm = return_matrices[ticker]
                if d in rm.index and entry_time in rm.columns:
                    val = rm.loc[d, entry_time]
                    if pd.notna(val):
                        rets[ticker] = val
            if len(rets) >= 20:  # need enough tickers for meaningful quintiles
                sorted_tickers = sorted(rets.keys(), key=lambda t: rets[t])
                laggards = sorted_tickers[:QUINTILE_SIZE]
                leaders = sorted_tickers[-QUINTILE_SIZE:]
                day_rankings[d] = {
                    "laggards": laggards,
                    "leaders": leaders,
                    "entry_rets": rets,
                }

        if not day_rankings:
            continue

        # Compute forward returns for each exit specification
        exit_specs = []
        # Relative exits: +1hr, +2hr, +3hr
        for minutes_fwd in EXIT_TIMES_RELATIVE:
            h = entry_time.hour + minutes_fwd // 60
            m = entry_time.minute + minutes_fwd % 60
            if m >= 60:
                h += 1
                m -= 60
            if h > 15 or (h == 15 and m > 55):
                # Cap at market close
                exit_t = dtime(15, 55)
                label = f"+{minutes_fwd//60}hr(capped)"
            else:
                exit_t = dtime(h, m)
                label = f"+{minutes_fwd//60}hr"
            exit_specs.append((exit_t, label))

        # Fixed exits
        for exit_t in EXIT_TIMES_FIXED:
            if exit_t <= entry_time:
                continue  # skip if exit before entry
            label = exit_t.strftime("%H:%M")
            exit_specs.append((exit_t, label))

        # Deduplicate exit specs
        seen = set()
        unique_exits = []
        for exit_t, label in exit_specs:
            key = (exit_t, label)
            if key not in seen:
                seen.add(key)
                unique_exits.append((exit_t, label))
        exit_specs = unique_exits

        for exit_t, exit_label in exit_specs:
            laggard_fwd = []
            leader_fwd = []
            spreads = []

            for d, ranking in day_rankings.items():
                lag_rets = []
                lead_rets = []

                for ticker in ranking["laggards"]:
                    rm = return_matrices[ticker]
                    if d in rm.index:
                        entry_ret = rm.loc[d, entry_time] if entry_time in rm.columns else np.nan
                        exit_ret = rm.loc[d, exit_t] if exit_t in rm.columns else np.nan
                        if pd.notna(entry_ret) and pd.notna(exit_ret):
                            # Forward return from entry to exit
                            fwd = exit_ret - entry_ret
                            lag_rets.append(fwd)

                for ticker in ranking["leaders"]:
                    rm = return_matrices[ticker]
                    if d in rm.index:
                        entry_ret = rm.loc[d, entry_time] if entry_time in rm.columns else np.nan
                        exit_ret = rm.loc[d, exit_t] if exit_t in rm.columns else np.nan
                        if pd.notna(entry_ret) and pd.notna(exit_ret):
                            fwd = exit_ret - entry_ret
                            lead_rets.append(fwd)

                if lag_rets and lead_rets:
                    avg_lag = np.mean(lag_rets)
                    avg_lead = np.mean(lead_rets)
                    laggard_fwd.append(avg_lag)
                    leader_fwd.append(avg_lead)
                    spreads.append(avg_lag - avg_lead)

            if len(spreads) >= 5:
                spread_arr = np.array(spreads)
                t_stat, p_val = stats.ttest_1samp(spread_arr, 0)
                win_rate = np.mean(spread_arr > 0) * 100

                results[(entry_time.strftime("%H:%M"), exit_label)] = {
                    "n": len(spreads),
                    "avg_laggard_fwd": np.mean(laggard_fwd),
                    "avg_leader_fwd": np.mean(leader_fwd),
                    "spread": np.mean(spreads),
                    "spread_std": np.std(spreads, ddof=1),
                    "t_stat": t_stat,
                    "p_val": p_val,
                    "win_rate": win_rate,
                    "spreads_list": spreads,  # for split-sample
                }

    return results


# ── Task 4: Split-Sample Validation ───────────────────────────────────────

def split_sample_validation(heat_map_results, stress_dates_sorted):
    """For cells meeting viability criteria, split chronologically and re-test."""
    n = len(stress_dates_sorted)
    if n < 10:
        return {}

    mid = n // 2
    # We need the actual spread per day — stored in spreads_list
    validations = {}

    for key, cell in heat_map_results.items():
        spread = cell["spread"]
        p_val = cell["p_val"]
        wr = cell["win_rate"]

        # Viability gate: spread > +0.30%, p < 0.10
        if spread > 0.30 and p_val < 0.10:
            spreads = cell["spreads_list"]
            first_half = spreads[:mid]
            second_half = spreads[mid:]

            fh_mean = np.mean(first_half) if first_half else np.nan
            sh_mean = np.mean(second_half) if second_half else np.nan
            stable = (fh_mean > 0.10 and sh_mean > 0.10) if (
                pd.notna(fh_mean) and pd.notna(sh_mean)) else False

            validations[key] = {
                "full_spread": spread,
                "first_half_spread": fh_mean,
                "second_half_spread": sh_mean,
                "first_half_n": len(first_half),
                "second_half_n": len(second_half),
                "stable": stable,
            }

    return validations


# ── Report Generation ─────────────────────────────────────────────────────

def format_heat_map_table(results, entry_times, exit_labels, title):
    """Format heat map as markdown table."""
    lines = [f"### {title}\n"]

    # Header
    header = "| Entry \\ Exit |"
    sep = "|:---|"
    for el in exit_labels:
        header += f" {el} |"
        sep += ":---:|"
    lines.append(header)
    lines.append(sep)

    for et in entry_times:
        et_str = et.strftime("%H:%M")
        row = f"| **{et_str}** |"
        for el in exit_labels:
            key = (et_str, el)
            if key in results:
                c = results[key]
                spread = c["spread"]
                p = c["p_val"]
                wr = c["win_rate"]
                # Mark viable cells
                marker = ""
                if spread > 0.30 and p < 0.10 and wr > 55:
                    marker = " **★**"
                row += f" {spread:+.3f}% (t={c['t_stat']:.2f}, p={p:.3f}, WR={wr:.0f}%, n={c['n']}){marker} |"
            else:
                row += " — |"
        lines.append(row)

    return "\n".join(lines)


def format_spread_only_table(results, entry_times, exit_labels, title):
    """Compact spread-only table."""
    lines = [f"### {title}\n"]
    header = "| Entry \\ Exit |"
    sep = "|:---|"
    for el in exit_labels:
        header += f" {el} |"
        sep += ":---:|"
    lines.append(header)
    lines.append(sep)

    for et in entry_times:
        et_str = et.strftime("%H:%M")
        row = f"| **{et_str}** |"
        for el in exit_labels:
            key = (et_str, el)
            if key in results:
                spread = results[key]["spread"]
                row += f" {spread:+.3f}% |"
            else:
                row += " — |"
        lines.append(row)

    return "\n".join(lines)


def generate_report(task1, stress_hm, nonstress_hm, diff_hm,
                    validations, stress_days_list, spy_rets):
    """Generate the full markdown report."""
    lines = []
    lines.append("# Stress MR v2 — Part 1: Heat Map Results")
    lines.append("")
    lines.append(f"**Generated:** 2026-03-24")
    lines.append(f"**Data:** M5 regular-session (09:30–15:55 ET), 25 equity tickers")
    lines.append(f"**Stress threshold:** median return < {STRESS_THRESHOLD}% at measurement time")
    lines.append(f"**Quintiles:** Bottom 5 (laggards) vs Top 5 (leaders) by return-from-open")
    lines.append("")

    # ── Task 1 ──
    lines.append("## Task 1: Stress Day Identification\n")
    lines.append("| Measurement Time | Stress Days (N) | % of Total Days | Avg SPY Return on Stress Days |")
    lines.append("|:---|:---:|:---:|:---:|")

    for mtime in MEASUREMENT_TIMES:
        df = task1[mtime]
        total = len(df.dropna(subset=["median_return"]))
        n_stress = df["is_stress"].sum()
        pct = n_stress / total * 100 if total > 0 else 0

        stress_dates = df[df["is_stress"]]["date"].tolist()
        spy_stress_rets = [spy_rets.get(d, np.nan) for d in stress_dates]
        spy_stress_rets = [r for r in spy_stress_rets if pd.notna(r)]
        avg_spy = np.mean(spy_stress_rets) if spy_stress_rets else np.nan

        lines.append(f"| {mtime.strftime('%H:%M')} ET | {n_stress} | {pct:.1f}% | "
                      f"{avg_spy:+.2f}% |" if pd.notna(avg_spy) else
                      f"| {mtime.strftime('%H:%M')} ET | {n_stress} | {pct:.1f}% | N/A |")

    # Stress day list (using 11:00 as primary)
    lines.append("")
    lines.append("### Stress Days (11:00 ET measurement)\n")
    df_11 = task1[dtime(11, 0)]
    stress_rows = df_11[df_11["is_stress"]].sort_values("date")
    if len(stress_rows) > 0:
        lines.append("| Date | Median Return at 11:00 | SPY Daily Return |")
        lines.append("|:---|:---:|:---:|")
        for _, row in stress_rows.iterrows():
            spy_r = spy_rets.get(row["date"], np.nan)
            spy_str = f"{spy_r:+.2f}%" if pd.notna(spy_r) else "N/A"
            lines.append(f"| {row['date']} | {row['median_return']:+.2f}% | {spy_str} |")
    else:
        lines.append("*No stress days identified at 11:00 ET.*")

    lines.append("")

    # ── Task 2 ──
    lines.append("## Task 2: Laggard-Leader Spread — Stress Days\n")

    # Determine exit labels from results
    exit_labels = _get_exit_labels(stress_hm)

    lines.append(format_heat_map_table(stress_hm, ENTRY_TIMES, exit_labels,
                                        "Full Detail: Spread (t-stat, p-value, WR, N)"))
    lines.append("")
    lines.append("**★ = Viable cell:** spread > +0.30%, p < 0.10, WR > 55%")
    lines.append("")

    # ── Task 3 ──
    lines.append("## Task 3: Laggard-Leader Spread — Non-Stress Days (Control)\n")
    exit_labels_ns = _get_exit_labels(nonstress_hm)
    # Use union of exit labels
    all_exits = list(dict.fromkeys(exit_labels + exit_labels_ns))

    lines.append(format_heat_map_table(nonstress_hm, ENTRY_TIMES, all_exits,
                                        "Full Detail: Spread (t-stat, p-value, WR, N)"))
    lines.append("")

    # Difference matrix
    lines.append("### Stress − Non-Stress Spread Difference\n")
    lines.append("| Entry \\ Exit |" + "".join(f" {el} |" for el in all_exits))
    lines.append("|:---|" + "".join(":---:|" for _ in all_exits))
    for et in ENTRY_TIMES:
        et_str = et.strftime("%H:%M")
        row = f"| **{et_str}** |"
        for el in all_exits:
            key = (et_str, el)
            s_spread = stress_hm[key]["spread"] if key in stress_hm else np.nan
            ns_spread = nonstress_hm[key]["spread"] if key in nonstress_hm else np.nan
            if pd.notna(s_spread) and pd.notna(ns_spread):
                diff = s_spread - ns_spread
                row += f" {diff:+.3f}% |"
            else:
                row += " — |"
        lines.append(row)

    lines.append("")

    # ── Task 4 ──
    lines.append("## Task 4: Split-Sample Validation\n")
    if validations:
        lines.append("| Cell (Entry×Exit) | Full Spread | First Half | Second Half | Stable? |")
        lines.append("|:---|:---:|:---:|:---:|:---:|")
        for key, v in validations.items():
            entry_str, exit_str = key
            stable_str = "YES" if v["stable"] else "NO"
            lines.append(f"| {entry_str}→{exit_str} | {v['full_spread']:+.3f}% | "
                          f"{v['first_half_spread']:+.3f}% (n={v['first_half_n']}) | "
                          f"{v['second_half_spread']:+.3f}% (n={v['second_half_n']}) | {stable_str} |")
    else:
        lines.append("*No cells met the viability threshold (spread > +0.30%, p < 0.10). "
                      "Split-sample validation not applicable.*")

    lines.append("")

    # ── Bottom Line ──
    lines.append("## Bottom Line\n")

    viable_cells = []
    for key, cell in stress_hm.items():
        if cell["spread"] > 0.30 and cell["p_val"] < 0.10 and cell["win_rate"] > 55:
            # Check if stable in split-sample
            if key in validations and validations[key]["stable"]:
                viable_cells.append((key, cell, validations[key]))

    fully_viable = len(viable_cells)
    marginal = sum(1 for k, c in stress_hm.items()
                   if c["spread"] > 0.30 and c["p_val"] < 0.10 and c["win_rate"] > 55)

    lines.append(f"- **Cells meeting initial criteria** (spread > +0.30%, p < 0.10, WR > 55%): "
                 f"**{marginal}**")
    lines.append(f"- **Cells surviving split-sample** (both halves > +0.10%): **{fully_viable}**")
    lines.append("")

    if fully_viable > 0:
        lines.append("### Viable Signals Found\n")
        for key, cell, val in viable_cells:
            lines.append(f"- **{key[0]} → {key[1]}**: spread {cell['spread']:+.3f}%, "
                          f"t={cell['t_stat']:.2f}, p={cell['p_val']:.3f}, "
                          f"WR={cell['win_rate']:.0f}%, n={cell['n']}")
            lines.append(f"  - First half: {val['first_half_spread']:+.3f}%, "
                          f"Second half: {val['second_half_spread']:+.3f}%")
        lines.append("")
        lines.append("**Verdict:** Signal detected. Proceed to Part 2 for transaction cost "
                      "analysis and alternative entry signals.")
    else:
        if marginal > 0:
            lines.append(f"**{marginal} cell(s) met initial criteria but FAILED split-sample "
                          "validation** — signal is not stable across time periods.\n")
        lines.append("**Verdict:** No viable intraday mean-reversion signal found on stress days. "
                      "The laggard-leader spread does not consistently exceed the +0.30% viability "
                      "threshold with statistical significance and temporal stability.\n")
        lines.append("**Recommendation:** Stress MR research line is closed. "
                      "The \"AM laggards revert in PM\" hypothesis does not survive clean data testing.")

    lines.append("")
    lines.append("---")
    lines.append(f"*Analysis: stress_mr_part1.py | Data: 25 tickers × M5 regular session | "
                 f"Threshold: median < {STRESS_THRESHOLD}% at measurement time*")

    return "\n".join(lines)


def _get_exit_labels(hm):
    """Extract ordered exit labels from heat map results."""
    labels = []
    seen = set()
    for (entry, exit_l) in sorted(hm.keys()):
        if exit_l not in seen:
            labels.append(exit_l)
            seen.add(exit_l)
    return labels


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("Stress MR v2 — Part 1: Heat Map Exploration")
    print("=" * 70)

    # Load data
    print("\n[1/5] Loading M5 data...")
    frames = load_all_m5()
    if len(frames) < 20:
        print(f"ERROR: Only {len(frames)} tickers loaded, need at least 20")
        sys.exit(1)

    print("\n[2/5] Building return matrices...")
    return_matrices, open_prices = build_return_matrix(frames)
    spy_daily_rets = get_spy_daily_returns(return_matrices)

    # Task 1: Stress day identification
    print("\n[3/5] Task 1: Identifying stress days...")
    task1 = identify_stress_days(return_matrices)

    for mtime in MEASUREMENT_TIMES:
        df = task1[mtime]
        n_stress = df["is_stress"].sum()
        total = len(df.dropna(subset=["median_return"]))
        print(f"  {mtime.strftime('%H:%M')} ET: {n_stress} stress days / {total} total "
              f"({n_stress/total*100:.1f}%)")

    # Use 11:00 ET as primary stress definition
    primary_stress_df = task1[dtime(11, 0)]
    stress_dates = set(primary_stress_df[primary_stress_df["is_stress"]]["date"].tolist())
    all_dates = set(primary_stress_df.dropna(subset=["median_return"])["date"].tolist())
    nonstress_dates = all_dates - stress_dates

    stress_dates_sorted = sorted(stress_dates)
    print(f"\n  Primary (11:00 ET): {len(stress_dates)} stress, "
          f"{len(nonstress_dates)} non-stress days")

    # Task 2: Stress heat map
    print("\n[4/5] Task 2: Computing stress-day heat map...")
    stress_hm = compute_heat_map(return_matrices, stress_dates, frames)
    print(f"  Computed {len(stress_hm)} cells")

    # Print summary of best cells
    if stress_hm:
        best_key = max(stress_hm, key=lambda k: stress_hm[k]["spread"])
        best = stress_hm[best_key]
        print(f"  Best cell: {best_key[0]}→{best_key[1]}: "
              f"spread={best['spread']:+.3f}%, t={best['t_stat']:.2f}, "
              f"p={best['p_val']:.3f}, WR={best['win_rate']:.0f}%")

    # Task 3: Non-stress control
    print("\n[4/5] Task 3: Computing non-stress control heat map...")
    nonstress_hm = compute_heat_map(return_matrices, nonstress_dates, frames)
    print(f"  Computed {len(nonstress_hm)} cells")

    # Difference matrix summary
    print("\n  Stress vs Non-Stress spread differences:")
    for key in sorted(stress_hm.keys()):
        if key in nonstress_hm:
            diff = stress_hm[key]["spread"] - nonstress_hm[key]["spread"]
            if abs(diff) > 0.15:
                print(f"    {key[0]}→{key[1]}: stress-nonstress = {diff:+.3f}%")

    # Task 4: Split-sample
    print("\n[5/5] Task 4: Split-sample validation...")
    validations = split_sample_validation(stress_hm, stress_dates_sorted)
    if validations:
        for key, v in validations.items():
            print(f"  {key[0]}→{key[1]}: full={v['full_spread']:+.3f}%, "
                  f"H1={v['first_half_spread']:+.3f}%, H2={v['second_half_spread']:+.3f}%, "
                  f"stable={'YES' if v['stable'] else 'NO'}")
    else:
        print("  No cells met viability threshold — split-sample not needed")

    # Compute difference heat map for report
    diff_hm = {}
    for key in stress_hm:
        if key in nonstress_hm:
            diff_hm[key] = {
                "spread": stress_hm[key]["spread"] - nonstress_hm[key]["spread"]
            }

    # Generate report
    print("\nGenerating report...")
    report = generate_report(task1, stress_hm, nonstress_hm, diff_hm,
                             validations, stress_dates_sorted, spy_daily_rets)

    output_path = OUTPUT_DIR / "PART1_HEAT_MAP_RESULTS.md"
    output_path.write_text(report)
    print(f"Report written to: {output_path}")

    # Also save raw results as JSON for downstream use
    raw_results = {
        "stress_days": [str(d) for d in stress_dates_sorted],
        "n_stress": len(stress_dates),
        "n_nonstress": len(nonstress_dates),
        "heat_map_stress": {
            f"{k[0]}__{k[1]}": {kk: vv for kk, vv in v.items() if kk != "spreads_list"}
            for k, v in stress_hm.items()
        },
        "heat_map_nonstress": {
            f"{k[0]}__{k[1]}": {kk: vv for kk, vv in v.items() if kk != "spreads_list"}
            for k, v in nonstress_hm.items()
        },
        "validations": {
            f"{k[0]}__{k[1]}": v for k, v in validations.items()
        },
    }
    json_path = OUTPUT_DIR / "part1_raw_results.json"
    with open(json_path, "w") as f:
        json.dump(raw_results, f, indent=2, default=str)
    print(f"Raw results saved to: {json_path}")

    # Final summary
    viable = sum(1 for k, c in stress_hm.items()
                 if c["spread"] > 0.30 and c["p_val"] < 0.10 and c["win_rate"] > 55
                 and k in validations and validations[k]["stable"])
    print(f"\n{'='*70}")
    print(f"BOTTOM LINE: {viable} viable cell(s) found")
    if viable == 0:
        print("No intraday MR signal on stress days. Research line closed.")
    else:
        print("Signal detected — proceed to Part 2.")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
