"""
PEAD Daily Baseline — Robustness Tests (Part 1c of 3).

Reads results/pead_events_daily.csv and tests top configurations from 1b:
  1. LOTO (Leave-One-Ticker-Out)
  2. LOYO (Leave-One-Year-Out)
  3. Temporal IS/OOS split
  4. VIX regime robustness
  5. Gap cap test
  6. Final verdict

Appends results to results/pead_daily_baseline.md.

Usage:
    python backtests/pead_daily_baseline_robust.py
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
# Configs to test — derived from 1b sweep top results
# ---------------------------------------------------------------------------
CONFIGS = [
    # Config A: Best overall — SHORT gap>=3%, first_bar_holds, 1d hold
    {"name": "SHORT_g3_fb_1d", "direction": "SHORT_ONLY", "gap_thr": 3.0,
     "surprise_thr": 0, "first_bar": True, "hold_days": 1},

    # Config B: High-N SHORT — gap>=1%, first_bar_holds, 1d hold (N=110)
    {"name": "SHORT_g1_fb_1d", "direction": "SHORT_ONLY", "gap_thr": 1.0,
     "surprise_thr": 0, "first_bar": True, "hold_days": 1},

    # Config C: Best LONG — gap>=3%, first_bar_holds, 1d hold
    {"name": "LONG_g3_fb_1d", "direction": "LONG_ONLY", "gap_thr": 3.0,
     "surprise_thr": 0, "first_bar": True, "hold_days": 1},

    # Config D: LONG gap>=2%, first_bar_holds, 5d hold (high-N LONG)
    {"name": "LONG_g2_fb_5d", "direction": "LONG_ONLY", "gap_thr": 2.0,
     "surprise_thr": 0, "first_bar": True, "hold_days": 5},

    # Config E: BOTH directions, gap>=3%, surprise>=5%, first_bar, 5d hold
    {"name": "BOTH_g3_s5_fb_5d", "direction": "BOTH", "gap_thr": 3.0,
     "surprise_thr": 5.0, "first_bar": True, "hold_days": 5},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def pf(returns: pd.Series) -> float:
    wins = returns[returns > 0].sum()
    losses = returns[returns < 0].sum()
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / abs(losses)


def wr(returns: pd.Series) -> float:
    if len(returns) == 0:
        return 0.0
    return (returns > 0).sum() / len(returns) * 100


def pval(returns: pd.Series) -> float:
    if len(returns) < 2:
        return np.nan
    _, p = scipy_stats.ttest_1samp(returns.dropna(), 0)
    return p


def fmt_pf(v):
    if np.isinf(v):
        return "inf"
    return f"{v:.2f}"


def fmt_p(v):
    if pd.isna(v):
        return "—"
    if v < 0.001:
        return "<.001"
    if v < 0.01:
        return f"{v:.3f}"
    return f"{v:.2f}"


def apply_config(df, cfg):
    """Filter df by config, return (filtered_df, returns Series)."""
    mask = df["gap_pct"].abs() >= cfg["gap_thr"]

    if cfg["direction"] == "LONG_ONLY":
        mask &= df["gap_pct"] > 0
    elif cfg["direction"] == "SHORT_ONLY":
        mask &= df["gap_pct"] < 0

    if cfg["surprise_thr"] > 0:
        mask &= df["eps_surprise_pct"].abs() >= cfg["surprise_thr"]

    if cfg["first_bar"]:
        mask &= df["first_bar_holds"]

    sub = df[mask].copy()
    drift_col = f"drift_{cfg['hold_days']}d"
    returns = sub[drift_col].dropna()

    if cfg["direction"] == "SHORT_ONLY":
        returns = -returns

    return sub, returns


def config_stats(returns):
    """Return dict of N, mean, WR, PF, p_value."""
    n = len(returns)
    if n == 0:
        return {"N": 0, "mean": np.nan, "WR": 0.0, "PF": 0.0, "p_value": np.nan}
    return {
        "N": n,
        "mean": returns.mean(),
        "WR": wr(returns),
        "PF": pf(returns),
        "p_value": pval(returns),
    }


# ---------------------------------------------------------------------------
# Section 1: LOTO
# ---------------------------------------------------------------------------
def section1_loto(df, out):
    out.write("\n---\n\n## Robustness — Section 1: LOTO (Leave-One-Ticker-Out)\n\n")

    verdicts = {}

    for cfg in CONFIGS:
        sub, full_ret = apply_config(df, cfg)
        full_stats = config_stats(full_ret)

        if full_stats["N"] < 5:
            out.write(f"### {cfg['name']}: N={full_stats['N']} — too few events, skipping.\n\n")
            verdicts[cfg["name"]] = ("SKIP", 0, "N/A")
            continue

        out.write(f"### {cfg['name']} (full: N={full_stats['N']}, "
                  f"PF={fmt_pf(full_stats['PF'])}, WR={full_stats['WR']:.1f}%)\n\n")

        # Tickers with >= 3 events in this config
        ticker_counts = sub["ticker"].value_counts()
        eligible = ticker_counts[ticker_counts >= 3].index.tolist()

        rows = []
        max_impact = 0.0
        max_ticker = ""

        for ticker in sorted(eligible):
            mask_out = sub["ticker"] != ticker
            sub_out = sub[mask_out]
            drift_col = f"drift_{cfg['hold_days']}d"
            ret_out = sub_out[drift_col].dropna()
            if cfg["direction"] == "SHORT_ONLY":
                ret_out = -ret_out

            st = config_stats(ret_out)
            n_removed = (sub["ticker"] == ticker).sum()

            if full_stats["PF"] > 0 and not np.isinf(full_stats["PF"]):
                impact = (full_stats["PF"] - st["PF"]) / full_stats["PF"] * 100
            else:
                impact = 0.0

            if abs(impact) > abs(max_impact):
                max_impact = impact
                max_ticker = ticker

            rows.append([
                ticker, n_removed, st["N"], fmt_pf(st["PF"]),
                f"{impact:+.1f}", f"{st['mean']:.3f}",
            ])

        tbl = tabulate(rows,
                       headers=["ticker", "N_rm", "N_left", "PF_without",
                                "PF_impact%", "mean_without%"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")

        robust = abs(max_impact) < 25
        verdict = "ROBUST" if robust else "FRAGILE"
        out.write(f"**LOTO verdict: {verdict}** (max impact: {max_impact:+.1f}%, ticker: {max_ticker})\n\n")
        verdicts[cfg["name"]] = (verdict, max_impact, max_ticker)

    return verdicts


# ---------------------------------------------------------------------------
# Section 2: LOYO
# ---------------------------------------------------------------------------
def section2_loyo(df, out):
    out.write("## Robustness — Section 2: LOYO (Leave-One-Year-Out)\n\n")

    verdicts = {}

    for cfg in CONFIGS:
        sub, full_ret = apply_config(df, cfg)
        full_stats = config_stats(full_ret)

        if full_stats["N"] < 5:
            out.write(f"### {cfg['name']}: skipping (N={full_stats['N']}).\n\n")
            verdicts[cfg["name"]] = ("SKIP", 0, "N/A")
            continue

        out.write(f"### {cfg['name']} (full: N={full_stats['N']}, "
                  f"PF={fmt_pf(full_stats['PF'])})\n\n")

        year_counts = sub["year"].value_counts()
        eligible_years = year_counts[year_counts >= 3].index.tolist()

        rows = []
        max_impact = 0.0
        max_year = 0

        for year in sorted(eligible_years):
            mask_out = sub["year"] != year
            sub_out = sub[mask_out]
            drift_col = f"drift_{cfg['hold_days']}d"
            ret_out = sub_out[drift_col].dropna()
            if cfg["direction"] == "SHORT_ONLY":
                ret_out = -ret_out

            st = config_stats(ret_out)
            n_removed = (sub["year"] == year).sum()

            if full_stats["PF"] > 0 and not np.isinf(full_stats["PF"]):
                impact = (full_stats["PF"] - st["PF"]) / full_stats["PF"] * 100
            else:
                impact = 0.0

            if abs(impact) > abs(max_impact):
                max_impact = impact
                max_year = year

            rows.append([
                year, n_removed, st["N"], fmt_pf(st["PF"]),
                f"{impact:+.1f}", f"{st['mean']:.3f}", f"{st['WR']:.1f}",
            ])

        tbl = tabulate(rows,
                       headers=["year", "N_rm", "N_left", "PF_without",
                                "PF_impact%", "mean%", "WR%"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")

        robust = abs(max_impact) < 30
        verdict = "ROBUST" if robust else "FRAGILE"
        out.write(f"**LOYO verdict: {verdict}** (max impact: {max_impact:+.1f}%, year: {max_year})\n\n")
        verdicts[cfg["name"]] = (verdict, max_impact, max_year)

    return verdicts


# ---------------------------------------------------------------------------
# Section 3: Temporal IS/OOS Split
# ---------------------------------------------------------------------------
def section3_isoos(df, out):
    out.write("## Robustness — Section 3: Temporal IS/OOS Split\n\n")

    # Data spans 2022-2026, so adapt splits to available range
    splits = [
        ("IS: 2022-2023 / OOS: 2024-2026", [2022, 2023], [2024, 2025, 2026]),
        ("IS: 2022-2024 / OOS: 2025-2026", [2022, 2023, 2024], [2025, 2026]),
    ]

    verdicts = {}

    for cfg in CONFIGS:
        out.write(f"### {cfg['name']}\n\n")

        cfg_verdicts = []
        rows = []
        for split_name, is_years, oos_years in splits:
            df_is = df[df["year"].isin(is_years)]
            df_oos = df[df["year"].isin(oos_years)]

            _, ret_is = apply_config(df_is, cfg)
            _, ret_oos = apply_config(df_oos, cfg)

            st_is = config_stats(ret_is)
            st_oos = config_stats(ret_oos)

            rows.append([
                split_name, "IS", st_is["N"], f"{st_is['mean']:.3f}",
                f"{st_is['WR']:.1f}", fmt_pf(st_is["PF"]),
            ])
            rows.append([
                "", "OOS", st_oos["N"], f"{st_oos['mean']:.3f}",
                f"{st_oos['WR']:.1f}", fmt_pf(st_oos["PF"]),
            ])

            # Determine verdict for this split
            if st_oos["N"] < 5:
                v = "INSUFFICIENT_DATA"
            elif st_oos["PF"] < 1.0:
                v = "REJECT"
            elif st_is["PF"] > 0 and not np.isinf(st_is["PF"]) and st_oos["PF"] < st_is["PF"] * 0.5:
                v = "CAUTION"
            else:
                v = "PASS"
            cfg_verdicts.append(v)

        tbl = tabulate(rows,
                       headers=["split", "set", "N", "mean%", "WR%", "PF"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")

        # Overall verdict: worst of the splits
        if "REJECT" in cfg_verdicts:
            verdict = "REJECT"
        elif "CAUTION" in cfg_verdicts:
            verdict = "CAUTION"
        elif "INSUFFICIENT_DATA" in cfg_verdicts:
            verdict = "INSUFFICIENT_DATA"
        else:
            verdict = "PASS"

        out.write(f"**IS/OOS verdict: {verdict}**\n\n")
        verdicts[cfg["name"]] = verdict

    return verdicts


# ---------------------------------------------------------------------------
# Section 4: VIX Regime Robustness
# ---------------------------------------------------------------------------
def section4_vix(df, out):
    out.write("## Robustness — Section 4: VIX Regime\n\n")

    regimes = [
        ("LOW (<20)", df["vix_on_day"] < 20),
        ("MEDIUM (20-25)", (df["vix_on_day"] >= 20) & (df["vix_on_day"] < 25)),
        ("HIGH (>=25)", df["vix_on_day"] >= 25),
    ]

    verdicts = {}

    for cfg in CONFIGS:
        out.write(f"### {cfg['name']}\n\n")

        rows = []
        regime_results = {}
        for regime_name, regime_mask in regimes:
            df_regime = df[regime_mask]
            _, ret = apply_config(df_regime, cfg)
            st = config_stats(ret)
            rows.append([
                regime_name, st["N"], f"{st['mean']:.3f}",
                f"{st['WR']:.1f}", fmt_pf(st["PF"]),
            ])
            regime_results[regime_name] = st

        tbl = tabulate(rows,
                       headers=["VIX regime", "N", "mean%", "WR%", "PF"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")

        # Verdict: edge works in >= 2 regimes with PF > 1.0
        working_regimes = sum(
            1 for st in regime_results.values()
            if st["N"] >= 5 and st["PF"] >= 1.0
        )
        verdict = "UNIVERSAL" if working_regimes >= 2 else "REGIME-DEPENDENT"
        out.write(f"**VIX verdict: {verdict}** ({working_regimes}/3 regimes with PF>=1.0)\n\n")
        verdicts[cfg["name"]] = verdict

    return verdicts


# ---------------------------------------------------------------------------
# Section 5: Gap Cap Test
# ---------------------------------------------------------------------------
def section5_gapcap(df, out):
    out.write("## Robustness — Section 5: Gap Cap Test\n\n")

    caps = [10, 15, 20, None]
    verdicts = {}

    for cfg in CONFIGS:
        out.write(f"### {cfg['name']}\n\n")

        rows = []
        best_pf = 0.0
        best_cap = None

        for cap in caps:
            if cap is not None:
                df_capped = df[df["gap_pct"].abs() <= cap]
            else:
                df_capped = df

            _, ret = apply_config(df_capped, cfg)
            st = config_stats(ret)

            cap_label = f"{cap}%" if cap else "no cap"
            rows.append([
                cap_label, st["N"], f"{st['mean']:.3f}",
                f"{st['WR']:.1f}", fmt_pf(st["PF"]),
            ])

            if st["N"] >= 10 and st["PF"] > best_pf and not np.isinf(st["PF"]):
                best_pf = st["PF"]
                best_cap = cap_label

        tbl = tabulate(rows,
                       headers=["gap_cap", "N", "mean%", "WR%", "PF"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")

        # Check if any cap materially improves PF
        _, full_ret = apply_config(df, cfg)
        full_pf = pf(full_ret)
        if not np.isinf(full_pf) and full_pf > 0:
            helps = best_pf > full_pf * 1.1
        else:
            helps = False

        verdict = f"HELPS (best: {best_cap})" if helps else "NO_EFFECT"
        out.write(f"**Gap cap verdict: {verdict}**\n\n")
        verdicts[cfg["name"]] = verdict

    return verdicts


# ---------------------------------------------------------------------------
# Section 6: Final Verdict
# ---------------------------------------------------------------------------
def section6_verdict(df, loto_v, loyo_v, isoos_v, vix_v, gapcap_v, out):
    out.write("## PEAD DAILY BASELINE — FINAL VERDICT\n\n")

    for cfg in CONFIGS:
        name = cfg["name"]
        _, full_ret = apply_config(df, cfg)
        st = config_stats(full_ret)

        out.write(f"### Config: {name}\n\n")
        out.write("```\n")
        out.write(f"N total:      {st['N']}\n")
        out.write(f"Performance:  mean {st['mean']:.3f}%, WR {st['WR']:.1f}%, "
                  f"PF {fmt_pf(st['PF'])}, p={fmt_p(st['p_value'])}\n")
        out.write(f"\n")

        loto_label, loto_impact, loto_item = loto_v.get(name, ("SKIP", 0, "N/A"))
        loyo_label, loyo_impact, loyo_item = loyo_v.get(name, ("SKIP", 0, "N/A"))
        isoos_label = isoos_v.get(name, "SKIP")
        vix_label = vix_v.get(name, "SKIP")
        gapcap_label = gapcap_v.get(name, "SKIP")

        out.write(f"LOTO:        {loto_label} (max impact {loto_impact:+.1f}%, ticker: {loto_item})\n")
        out.write(f"LOYO:        {loyo_label} (max impact {loyo_impact:+.1f}%, year: {loyo_item})\n")
        out.write(f"IS/OOS:      {isoos_label}\n")
        out.write(f"VIX regime:  {vix_label}\n")
        out.write(f"Gap cap:     {gapcap_label}\n")
        out.write(f"\n")

        # Overall verdict
        failures = 0
        if loto_label == "FRAGILE":
            failures += 1
        if loyo_label == "FRAGILE":
            failures += 1
        if isoos_label == "REJECT":
            failures += 1
        if isoos_label == "CAUTION":
            failures += 0.5

        if st["N"] < 30 or st["PF"] < 1.0:
            overall = "REJECT"
            reason = f"N={st['N']}, PF={fmt_pf(st['PF'])} — insufficient"
        elif failures >= 2:
            overall = "REJECT"
            reason = f"{int(failures)} robustness failures"
        elif st["N"] >= 40 and st["PF"] >= 1.5 and st["WR"] >= 55 and failures == 0:
            overall = "PROMISING"
            reason = "passes all criteria"
        elif st["N"] >= 30:
            overall = "MARGINAL"
            reasons = []
            if st["N"] < 40:
                reasons.append(f"N={st['N']}<40")
            if st["PF"] < 1.5:
                reasons.append(f"PF={fmt_pf(st['PF'])}<1.5")
            if st["WR"] < 55:
                reasons.append(f"WR={st['WR']:.1f}%<55%")
            if failures > 0:
                reasons.append(f"robustness concern")
            reason = ", ".join(reasons) if reasons else "borderline"
        else:
            overall = "REJECT"
            reason = "does not meet minimum criteria"

        out.write(f"OVERALL:     {overall}\n")
        out.write(f"Reason:      {reason}\n")

        # Next step
        if overall == "PROMISING":
            next_step = "Proceed to mechanical spec for Module 5 integration."
        elif overall == "MARGINAL":
            next_step = "Consider relaxing filters for more N, or combine with other signals."
        else:
            next_step = "Do not deploy. Re-examine with different parameters or data."
        out.write(f"Next step:   {next_step}\n")
        out.write("```\n\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    df = pd.read_csv(INPUT_CSV)
    print(f"Loaded {len(df)} events from {INPUT_CSV.name}")
    print(f"Years: {sorted(df['year'].unique())}, Tickers: {df['ticker'].nunique()}")
    print()

    # Preview config sizes
    for cfg in CONFIGS:
        _, ret = apply_config(df, cfg)
        st = config_stats(ret)
        print(f"  {cfg['name']:25s}  N={st['N']:4d}  mean={st['mean']:+.3f}%  "
              f"WR={st['WR']:.1f}%  PF={fmt_pf(st['PF'])}")
    print()

    md = StringIO()

    # Run all sections
    loto_v = section1_loto(df, md)
    loyo_v = section2_loyo(df, md)
    isoos_v = section3_isoos(df, md)
    vix_v = section4_vix(df, md)
    gapcap_v = section5_gapcap(df, md)
    section6_verdict(df, loto_v, loyo_v, isoos_v, vix_v, gapcap_v, md)

    content = md.getvalue()
    print(content)

    # Append to existing markdown
    with open(OUTPUT_MD, "a") as f:
        f.write("\n" + content)

    print(f"\nAppended robustness results → {OUTPUT_MD}")


if __name__ == "__main__":
    main()
