"""
PEAD Entry-Corrected Retest (CC-PEAD-2).

Fixes measurement bug from CC-PEAD-1: prior test measured drift from
prior_close, but first_bar_holds signal is only known at event_close.
This script recomputes all returns from the actual tradable entry point.

Reads:  results/pead_events_daily.csv
        backtester/data/daily/{TICKER}_daily.csv

Produces:
  results/pead_events_corrected.csv
  results/pead_entry_corrected.md

Usage:
    python backtests/pead_entry_corrected.py
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
DAILY_DIR = _REPO_ROOT / "backtester" / "data" / "daily"
OUTPUT_CSV = _REPO_ROOT / "results" / "pead_events_corrected.csv"
OUTPUT_MD = _REPO_ROOT / "results" / "pead_entry_corrected.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def pf(r):
    w = r[r > 0].sum()
    l = r[r < 0].sum()
    if l == 0:
        return float("inf") if w > 0 else 0.0
    return w / abs(l)


def wr(r):
    return (r > 0).sum() / len(r) * 100 if len(r) else 0.0


def pval(r):
    if len(r) < 2:
        return np.nan
    _, p = scipy_stats.ttest_1samp(r.dropna(), 0)
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
# Load daily price data
# ---------------------------------------------------------------------------
def load_daily(ticker):
    """Load daily CSV for a ticker, return DataFrame indexed by date."""
    path = DAILY_DIR / f"{ticker}_daily.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, header=[0, 1], index_col=0)
    df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    df.index.name = "Date"
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["Close"], inplace=True)
    return df


def offset_day(dt, idx, n):
    """Return the trading day n positions after dt in idx."""
    try:
        pos = idx.get_loc(pd.Timestamp(dt))
    except KeyError:
        return None
    target = pos + n
    if 0 <= target < len(idx):
        return idx[target]
    return None


# ---------------------------------------------------------------------------
# Step 1: Add corrected return columns
# ---------------------------------------------------------------------------
def add_corrected_columns(df):
    """Add tradable return columns to the events DataFrame."""
    print("Loading daily price data for corrected returns...")

    # Load all ticker data
    price_cache = {}
    tickers = df["ticker"].unique()
    for t in tickers:
        px = load_daily(t)
        if px is not None:
            price_cache[t] = px

    # Load SPY for market-adjusted
    spy = load_daily("SPY")
    if spy is not None:
        print(f"  SPY: {len(spy)} bars")
    else:
        print("  SPY: NOT FOUND — market-adjusted returns unavailable")

    # New columns
    new_cols = {
        "next_open": [], "next_close": [],
        "ret_ec_nc": [], "ret_no_nc": [], "ret_ec_no": [],
        "drift_2d_corr": [], "drift_3d_corr": [], "drift_5d_corr": [],
        "ret_ec_nc_adj": [], "ret_no_nc_adj": [],
        "spy_ret_ec_nc": [], "spy_ret_no_nc": [],
    }

    skipped = 0
    for _, row in df.iterrows():
        ticker = row["ticker"]
        event_day = pd.Timestamp(row["event_day"])
        event_close = row["event_close"]

        px = price_cache.get(ticker)
        if px is None or event_day not in px.index:
            for k in new_cols:
                new_cols[k].append(np.nan)
            skipped += 1
            continue

        idx = px.index

        # Next trading day after event_day
        nd = offset_day(event_day, idx, 1)

        if nd is None:
            for k in new_cols:
                new_cols[k].append(np.nan)
            skipped += 1
            continue

        n_open = float(px.loc[nd, "Open"])
        n_close = float(px.loc[nd, "Close"])

        # Core corrected returns
        ret_ec_nc = (n_close - event_close) / event_close * 100
        ret_no_nc = (n_close - n_open) / n_open * 100 if n_open != 0 else np.nan
        ret_ec_no = (n_open - event_close) / event_close * 100

        new_cols["next_open"].append(round(n_open, 4))
        new_cols["next_close"].append(round(n_close, 4))
        new_cols["ret_ec_nc"].append(round(ret_ec_nc, 4))
        new_cols["ret_no_nc"].append(round(ret_no_nc, 4))
        new_cols["ret_ec_no"].append(round(ret_ec_no, 4))

        # Multi-day corrected drifts from event_close
        for n_days, col_name in [(2, "drift_2d_corr"), (3, "drift_3d_corr"),
                                  (5, "drift_5d_corr")]:
            future = offset_day(event_day, idx, n_days)
            if future is not None:
                fc = float(px.loc[future, "Close"])
                new_cols[col_name].append(round((fc - event_close) / event_close * 100, 4))
            else:
                new_cols[col_name].append(np.nan)

        # SPY market-adjusted
        if spy is not None and event_day in spy.index:
            spy_idx = spy.index
            spy_nd = offset_day(event_day, spy_idx, 1)
            if spy_nd is not None:
                spy_ec = float(spy.loc[event_day, "Close"])
                spy_nc = float(spy.loc[spy_nd, "Close"])
                spy_no = float(spy.loc[spy_nd, "Open"])
                spy_ret_ec_nc = (spy_nc - spy_ec) / spy_ec * 100
                spy_ret_no_nc = (spy_nc - spy_no) / spy_no * 100 if spy_no != 0 else np.nan
                new_cols["ret_ec_nc_adj"].append(round(ret_ec_nc - spy_ret_ec_nc, 4))
                new_cols["ret_no_nc_adj"].append(
                    round(ret_no_nc - spy_ret_no_nc, 4) if not np.isnan(ret_no_nc) and not np.isnan(spy_ret_no_nc) else np.nan)
                new_cols["spy_ret_ec_nc"].append(round(spy_ret_ec_nc, 4))
                new_cols["spy_ret_no_nc"].append(round(spy_ret_no_nc, 4))
            else:
                for k in ["ret_ec_nc_adj", "ret_no_nc_adj", "spy_ret_ec_nc", "spy_ret_no_nc"]:
                    new_cols[k].append(np.nan)
        else:
            for k in ["ret_ec_nc_adj", "ret_no_nc_adj", "spy_ret_ec_nc", "spy_ret_no_nc"]:
                new_cols[k].append(np.nan)

    for k, v in new_cols.items():
        df[k] = v

    print(f"  Corrected columns added. Skipped {skipped}/{len(df)} events.")
    return df


# ---------------------------------------------------------------------------
# Config application
# ---------------------------------------------------------------------------
CONFIGS = [
    {"name": "SHORT_g1_fb_ec_nc", "direction": "SHORT", "gap_thr": 1.0,
     "first_bar": True, "return_col": "ret_ec_nc"},
    {"name": "SHORT_g1_fb_no_nc", "direction": "SHORT", "gap_thr": 1.0,
     "first_bar": True, "return_col": "ret_no_nc"},
    {"name": "SHORT_g3_fb_ec_nc", "direction": "SHORT", "gap_thr": 3.0,
     "first_bar": True, "return_col": "ret_ec_nc"},
    {"name": "SHORT_g1_fb_ec_nc_adj", "direction": "SHORT", "gap_thr": 1.0,
     "first_bar": True, "return_col": "ret_ec_nc_adj"},
    {"name": "LONG_g2_fb_5d_corr", "direction": "LONG", "gap_thr": 2.0,
     "first_bar": True, "return_col": "drift_5d_corr"},
    {"name": "LONG_g3_fb_5d_corr", "direction": "LONG", "gap_thr": 3.0,
     "first_bar": True, "return_col": "drift_5d_corr"},
    {"name": "BOTH_g3_fb_3d_corr", "direction": "BOTH", "gap_thr": 3.0,
     "first_bar": True, "return_col": "drift_3d_corr"},
]


def apply_config(df, cfg):
    """Filter df by config, return returns Series (sign-adjusted)."""
    mask = df["gap_pct"].abs() >= cfg["gap_thr"]

    if cfg["direction"] == "LONG":
        mask &= df["gap_pct"] > 0
    elif cfg["direction"] == "SHORT":
        mask &= df["gap_pct"] < 0

    if cfg["first_bar"]:
        mask &= df["first_bar_holds"]

    sub = df[mask].copy()
    ret = sub[cfg["return_col"]].dropna()

    if cfg["direction"] == "SHORT":
        ret = -ret

    return sub, ret


def config_stats(ret):
    n = len(ret)
    if n == 0:
        return {"N": 0, "mean": np.nan, "median": np.nan, "WR": 0,
                "PF": 0, "p_value": np.nan, "losers": 0, "max_loss": np.nan}
    return {
        "N": n, "mean": ret.mean(), "median": ret.median(),
        "WR": wr(ret), "PF": pf(ret), "p_value": pval(ret),
        "losers": (ret < 0).sum(),
        "max_loss": ret.min() if (ret < 0).any() else 0.0,
    }


# ---------------------------------------------------------------------------
# Step 3: Rerun key configs
# ---------------------------------------------------------------------------
def step3_configs(df, out):
    out.write("## Step 3: Corrected Config Results\n\n")

    rows = []
    for cfg in CONFIGS:
        _, ret = apply_config(df, cfg)
        st = config_stats(ret)
        rows.append([
            cfg["name"], st["N"], f"{st['mean']:.3f}" if not np.isnan(st["mean"]) else "—",
            f"{st['median']:.3f}" if not np.isnan(st["median"]) else "—",
            f"{st['WR']:.1f}", fmt_pf(st["PF"]),
            fmt_p(st["p_value"]), st["losers"],
            f"{st['max_loss']:.2f}" if not np.isnan(st["max_loss"]) else "—",
        ])

    tbl = tabulate(rows,
                   headers=["Config", "N", "Mean%", "Med%", "WR%", "PF",
                            "p-val", "Losers", "MaxLoss%"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")


# ---------------------------------------------------------------------------
# Step 2 + 6: AMC vs BMO
# ---------------------------------------------------------------------------
def step_amc_bmo(df, out):
    out.write("## Step 2/6: AMC vs BMO Breakdown\n\n")

    for cfg in CONFIGS:
        rows = []
        for tod in ["AMC", "BMO", "ALL"]:
            if tod == "ALL":
                sub_df = df
            else:
                sub_df = df[df["time_of_day"] == tod]
            _, ret = apply_config(sub_df, cfg)
            st = config_stats(ret)
            rows.append([
                tod, st["N"],
                f"{st['mean']:.3f}" if not np.isnan(st["mean"]) else "—",
                f"{st['WR']:.1f}", fmt_pf(st["PF"]),
            ])

        out.write(f"### {cfg['name']}\n\n")
        tbl = tabulate(rows, headers=["ToD", "N", "Mean%", "WR%", "PF"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")


# ---------------------------------------------------------------------------
# Step 4: Bootstrap
# ---------------------------------------------------------------------------
def step4_bootstrap(df, out):
    out.write("## Step 4: Corrected Bootstrap\n\n")

    rng = np.random.RandomState(42)
    n_boot = 10_000

    # Find top 3 by PF with N >= 20
    results = []
    for cfg in CONFIGS:
        _, ret = apply_config(df, cfg)
        st = config_stats(ret)
        if st["N"] >= 20:
            results.append((cfg, st, ret))

    results.sort(key=lambda x: x[1]["PF"], reverse=True)
    top3 = results[:3]

    if not top3:
        out.write("No configs with N >= 20.\n\n")
        return

    rows = []
    for cfg, st, actual_ret in top3:
        ret_col = cfg["return_col"]
        pool = df[ret_col].dropna().values
        if cfg["direction"] == "SHORT":
            pool = -pool
        n = st["N"]
        actual_mean = st["mean"]

        boot_means = np.array([
            rng.choice(pool, size=n, replace=True).mean()
            for _ in range(n_boot)
        ])
        pctile = (boot_means < actual_mean).sum() / n_boot * 100
        boot_p = 2 * min(pctile, 100 - pctile) / 100

        rows.append([
            cfg["name"], n, f"{actual_mean:.3f}",
            f"{boot_means.mean():.3f}", f"{boot_means.std():.3f}",
            f"{pctile:.1f}", f"{boot_p:.3f}",
        ])

    tbl = tabulate(rows,
                   headers=["config", "N", "actual%", "rand%", "rand_std%",
                            "pctile", "boot_p"],
                   tablefmt="pipe")
    out.write(tbl + "\n\n")


# ---------------------------------------------------------------------------
# Step 5: LOTO + IS/OOS + LOYO
# ---------------------------------------------------------------------------
def step5_robustness(df, out):
    out.write("## Step 5: Corrected LOTO + LOYO + IS/OOS\n\n")

    # Only test configs with N >= 20 and PF >= 1.5
    eligible = []
    for cfg in CONFIGS:
        _, ret = apply_config(df, cfg)
        st = config_stats(ret)
        if st["N"] >= 20 and st["PF"] >= 1.5:
            eligible.append((cfg, st))

    if not eligible:
        out.write("No configs pass N>=20 + PF>=1.5 for robustness testing.\n\n")
        return {}

    verdicts = {}

    for cfg, full_st in eligible:
        name = cfg["name"]
        out.write(f"### {name} (N={full_st['N']}, PF={fmt_pf(full_st['PF'])})\n\n")

        # --- LOTO ---
        out.write("**LOTO:**\n\n")
        sub_full, _ = apply_config(df, cfg)
        ticker_counts = sub_full["ticker"].value_counts()
        eligible_tickers = ticker_counts[ticker_counts >= 3].index.tolist()

        rows = []
        max_impact = 0.0
        max_ticker = ""
        for ticker in sorted(eligible_tickers):
            df_out = df[df["ticker"] != ticker]
            _, ret_out = apply_config(df_out, cfg)
            st_out = config_stats(ret_out)
            n_rm = (sub_full["ticker"] == ticker).sum()
            if full_st["PF"] > 0 and not np.isinf(full_st["PF"]):
                impact = (full_st["PF"] - st_out["PF"]) / full_st["PF"] * 100
            else:
                impact = 0.0
            if abs(impact) > abs(max_impact):
                max_impact = impact
                max_ticker = ticker
            rows.append([ticker, n_rm, st_out["N"], fmt_pf(st_out["PF"]),
                         f"{impact:+.1f}", f"{st_out['mean']:.3f}"])

        tbl = tabulate(rows,
                       headers=["ticker", "N_rm", "N_left", "PF", "impact%", "mean%"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")
        loto_v = "ROBUST" if abs(max_impact) < 25 else "FRAGILE"
        out.write(f"LOTO: **{loto_v}** (max: {max_impact:+.1f}%, {max_ticker})\n\n")

        # --- LOYO ---
        out.write("**LOYO:**\n\n")
        year_counts = sub_full["year"].value_counts()
        eligible_years = year_counts[year_counts >= 3].index.tolist()

        rows = []
        max_y_impact = 0.0
        max_year = 0
        for year in sorted(eligible_years):
            df_out = df[df["year"] != year]
            _, ret_out = apply_config(df_out, cfg)
            st_out = config_stats(ret_out)
            n_rm = (sub_full["year"] == year).sum()
            if full_st["PF"] > 0 and not np.isinf(full_st["PF"]):
                impact = (full_st["PF"] - st_out["PF"]) / full_st["PF"] * 100
            else:
                impact = 0.0
            if abs(impact) > abs(max_y_impact):
                max_y_impact = impact
                max_year = year
            rows.append([year, n_rm, st_out["N"], fmt_pf(st_out["PF"]),
                         f"{impact:+.1f}", f"{st_out['mean']:.3f}", f"{st_out['WR']:.1f}"])

        tbl = tabulate(rows,
                       headers=["year", "N_rm", "N_left", "PF", "impact%", "mean%", "WR%"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")
        loyo_v = "ROBUST" if abs(max_y_impact) < 30 else "FRAGILE"
        out.write(f"LOYO: **{loyo_v}** (max: {max_y_impact:+.1f}%, {max_year})\n\n")

        # --- IS/OOS ---
        out.write("**IS/OOS (2022-2023 vs 2024-2026):**\n\n")
        df_is = df[df["year"].isin([2022, 2023])]
        df_oos = df[df["year"].isin([2024, 2025, 2026])]
        _, ret_is = apply_config(df_is, cfg)
        _, ret_oos = apply_config(df_oos, cfg)
        st_is = config_stats(ret_is)
        st_oos = config_stats(ret_oos)

        rows = [
            ["IS (22-23)", st_is["N"], f"{st_is['mean']:.3f}",
             f"{st_is['WR']:.1f}", fmt_pf(st_is["PF"])],
            ["OOS (24-26)", st_oos["N"], f"{st_oos['mean']:.3f}",
             f"{st_oos['WR']:.1f}", fmt_pf(st_oos["PF"])],
        ]
        tbl = tabulate(rows, headers=["set", "N", "mean%", "WR%", "PF"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")

        if st_oos["N"] < 5:
            isoos_v = "INSUFFICIENT_DATA"
        elif st_oos["PF"] < 1.0:
            isoos_v = "REJECT"
        elif (st_is["PF"] > 0 and not np.isinf(st_is["PF"])
              and st_oos["PF"] < st_is["PF"] * 0.5):
            isoos_v = "CAUTION"
        else:
            isoos_v = "PASS"
        out.write(f"IS/OOS: **{isoos_v}**\n\n")

        verdicts[name] = {
            "loto": loto_v, "loto_impact": max_impact, "loto_ticker": max_ticker,
            "loyo": loyo_v, "loyo_impact": max_y_impact, "loyo_year": max_year,
            "isoos": isoos_v,
        }

    return verdicts


# ---------------------------------------------------------------------------
# Step 7: Overnight vs Intraday decomposition
# ---------------------------------------------------------------------------
def step7_decomposition(df, out):
    out.write("## Step 7: Overnight vs Intraday Decomposition\n\n")

    short_cfgs = [c for c in CONFIGS if c["direction"] == "SHORT"]

    for cfg in short_cfgs:
        sub, _ = apply_config(df, cfg)
        # For SHORT: negative price move = profit. Show raw (unsigned) for decomposition.
        overnight = -sub["ret_ec_no"].dropna()  # negate for SHORT perspective
        intraday = -sub["ret_no_nc"].dropna()
        total = -sub["ret_ec_nc"].dropna()

        out.write(f"### {cfg['name']} (N={len(total)})\n\n")
        rows = [
            ["Overnight (ec→no)", len(overnight), f"{overnight.mean():.3f}",
             f"{wr(overnight):.1f}", fmt_pf(pf(overnight))],
            ["Intraday (no→nc)", len(intraday), f"{intraday.mean():.3f}",
             f"{wr(intraday):.1f}", fmt_pf(pf(intraday))],
            ["Total (ec→nc)", len(total), f"{total.mean():.3f}",
             f"{wr(total):.1f}", fmt_pf(pf(total))],
        ]
        tbl = tabulate(rows, headers=["window", "N", "mean%", "WR%", "PF"],
                       tablefmt="pipe")
        out.write(tbl + "\n\n")

        if len(overnight) > 0 and len(intraday) > 0:
            ovn_share = abs(overnight.mean()) / (abs(overnight.mean()) + abs(intraday.mean())) * 100 \
                if (abs(overnight.mean()) + abs(intraday.mean())) > 0 else 50
            dominant = "OVERNIGHT" if ovn_share > 60 else ("INTRADAY" if ovn_share < 40 else "BOTH")
            out.write(f"Edge source: **{dominant}** (overnight: {ovn_share:.0f}%)\n\n")


# ---------------------------------------------------------------------------
# Step 8: Final verdict
# ---------------------------------------------------------------------------
def step8_verdict(df, robustness_v, out):
    out.write("## PEAD ENTRY-CORRECTED RETEST — FINAL VERDICT\n\n")

    # Contamination check
    out.write("### Contamination Check\n\n")
    out.write("```\n")

    # Old best: SHORT_g1_fb from prior test (drift from prior_close)
    mask_old = (df["gap_pct"].abs() >= 1.0) & (df["gap_pct"] < 0) & df["first_bar_holds"]
    old_ret = -df.loc[mask_old, "drift_1d"].dropna()
    old_st = config_stats(old_ret)
    out.write(f"Old best (SHORT_g1_fb, drift_1d from prior_close):\n")
    out.write(f"  N={old_st['N']}, Mean={old_st['mean']:.3f}%, "
              f"WR={old_st['WR']:.1f}%, PF={fmt_pf(old_st['PF'])}\n\n")

    # Corrected: same filter but event_close entry
    _, corr_ret = apply_config(df, CONFIGS[0])  # SHORT_g1_fb_ec_nc
    corr_st = config_stats(corr_ret)
    out.write(f"Corrected (SHORT_g1_fb, event_close→next_close):\n")
    out.write(f"  N={corr_st['N']}, Mean={corr_st['mean']:.3f}%, "
              f"WR={corr_st['WR']:.1f}%, PF={fmt_pf(corr_st['PF'])}\n\n")

    if old_st["PF"] > 0 and not np.isinf(old_st["PF"]):
        degrad = (1 - corr_st["PF"] / old_st["PF"]) * 100
        out.write(f"PF degradation: {degrad:.1f}%\n")
    out.write("```\n\n")

    # Best corrected config
    out.write("### Best Corrected Configs\n\n")
    best_cfgs = []
    for cfg in CONFIGS:
        _, ret = apply_config(df, cfg)
        st = config_stats(ret)
        best_cfgs.append((cfg, st, ret))

    best_cfgs.sort(key=lambda x: x[1]["PF"] if not np.isinf(x[1]["PF"]) else 9999, reverse=True)

    out.write("```\n")
    for cfg, st, _ in best_cfgs:
        name = cfg["name"]
        rob = robustness_v.get(name, {})
        loto = rob.get("loto", "—")
        isoos = rob.get("isoos", "—")

        out.write(f"\nConfig: {name}\n")
        out.write(f"  N={st['N']}, Mean={st['mean']:.3f}%, WR={st['WR']:.1f}%, "
                  f"PF={fmt_pf(st['PF'])}, p={fmt_p(st['p_value'])}\n")
        out.write(f"  LOTO: {loto}  |  IS/OOS: {isoos}\n")

        # Overall
        if st["N"] < 20 or st["PF"] < 1.0:
            overall = "REJECT"
        elif st["N"] >= 30 and st["PF"] >= 1.5 and st["WR"] >= 55:
            if loto == "ROBUST" and isoos == "PASS":
                overall = "VALIDATED"
            elif loto == "FRAGILE" or isoos in ("REJECT", "CAUTION"):
                overall = "MARGINAL"
            else:
                overall = "PROMISING"
        elif st["N"] >= 20 and st["PF"] >= 1.5:
            overall = "PROMISING (needs more N)"
        else:
            overall = "MARGINAL"

        out.write(f"  OVERALL: {overall}\n")

    out.write("```\n\n")

    # Recommendation
    out.write("### Recommendation\n\n")
    top = best_cfgs[0]
    top_st = top[1]
    if top_st["PF"] < 1.0:
        out.write("**REJECT**: Corrected returns show no tradable edge. "
                  "The apparent PEAD SHORT signal was a measurement artifact "
                  "(returns included the gap itself, which occurs before signal).\n")
    elif top_st["PF"] < 1.5:
        out.write("**MARGINAL**: Corrected edge exists but is weak (PF < 1.5). "
                  "Consider combining with additional filters or signals.\n")
    else:
        out.write(f"**PROMISING**: Best config {top[0]['name']} shows PF={fmt_pf(top_st['PF'])} "
                  f"with N={top_st['N']} after entry correction. "
                  f"Proceed to mechanical spec with realistic execution assumptions.\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    df = pd.read_csv(INPUT_CSV)
    print(f"Loaded {len(df)} events from {INPUT_CSV.name}")

    # Step 1: add corrected columns
    df = add_corrected_columns(df)

    # Save enhanced CSV
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved corrected CSV → {OUTPUT_CSV} ({len(df.columns)} cols)")

    md = StringIO()
    md.write("# PEAD Entry-Corrected Retest (CC-PEAD-2)\n\n")
    md.write("Fixes measurement bug: returns now computed from event_close "
             "(when signal is known), not prior_close.\n\n")

    # Step 3: config results
    step3_configs(df, md)

    # Step 2/6: AMC vs BMO
    step_amc_bmo(df, md)

    # Step 4: bootstrap
    step4_bootstrap(df, md)

    # Step 5: LOTO + LOYO + IS/OOS
    rob_v = step5_robustness(df, md)

    # Step 7: overnight vs intraday
    step7_decomposition(df, md)

    # Step 8: final verdict
    step8_verdict(df, rob_v, md)

    content = md.getvalue()
    print(content)

    OUTPUT_MD.write_text(content)
    print(f"\nSaved → {OUTPUT_MD}")


if __name__ == "__main__":
    main()
