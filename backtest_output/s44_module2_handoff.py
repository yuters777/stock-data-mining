#!/usr/bin/env python3
"""
S44 Module 2 — Part 3/3: Module 4 → Module 2 Handoff Analysis.

Detects Module 4 triggers (3 consecutive 4H down bars, VIX>=25),
tracks their exit (4H high >= EMA21), then checks whether the ticker
transitions into a 4H uptrend (EMA9 > EMA21 = Module 2 territory).

Tasks:
  A: Handoff rate and timing distribution
  B: Post-handoff forward returns vs regular Module 2 control
  C: VIX transition analysis

Output: results/S44_Module2_Part3_Handoff_Results.md
"""

import sys
from pathlib import Path
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Config ────────────────────────────────────────────────────────────────────

TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C",
    "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT",
    "MSTR", "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]

INDICATORS_4H_DIR = ROOT / "data" / "indicators_4h"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

VIX_THRESHOLD = 25.0
STREAK_LEN = 3
HANDOFF_SCAN_WINDOW = 10  # 4H bars after M4 exit to look for gate flip

# Forward return horizons (in 4H bars)
FWD_HORIZONS = [1, 2, 3, 5]


# ── Data loading ──────────────────────────────────────────────────────────────

def load_vix_daily():
    df = pd.read_csv(VIX_PATH)
    vix = {}
    for _, row in df.iterrows():
        try:
            val = float(row["VIXCLS"])
            vix[str(row["observation_date"])] = val
        except (ValueError, TypeError):
            continue
    return vix


def load_vix_series():
    """VIX as forward-filled daily Series for value lookups."""
    df = pd.read_csv(VIX_PATH)
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    df = df.dropna(subset=["VIXCLS"])
    df = df.set_index("observation_date").sort_index()
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="D"), method="ffill")
    return df["VIXCLS"]


def load_4h_bars(ticker):
    path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["is_down"] = df["close"] < df["open"]
    return df


def get_prior_vix(vix_daily, date_str):
    dt = pd.Timestamp(date_str)
    for offset in range(1, 6):
        prior = (dt - timedelta(days=offset)).strftime("%Y-%m-%d")
        if prior in vix_daily:
            return vix_daily[prior]
    return None


def get_vix_at_date(vix_series, date_str):
    """Get VIX value on a specific date (or nearest prior)."""
    ts = pd.Timestamp(date_str)
    for offset in range(4):
        lookup = ts - pd.Timedelta(days=offset)
        if lookup in vix_series.index:
            return vix_series[lookup]
    return None


# ── Module 4 trigger detection ────────────────────────────────────────────────

def detect_m4_triggers(bars_4h, vix_daily):
    """3 consecutive 4H down bars with prior-day VIX >= 25."""
    triggers = []
    for i in range(STREAK_LEN - 1, len(bars_4h)):
        streak_ok = all(bars_4h.iloc[i - j]["is_down"] for j in range(STREAK_LEN))
        if not streak_ok:
            continue

        trigger_bar = bars_4h.iloc[i]
        vix_val = get_prior_vix(vix_daily, trigger_bar["date_str"])
        if vix_val is None or vix_val < VIX_THRESHOLD:
            continue

        triggers.append({
            "idx": i,
            "timestamp": trigger_bar["timestamp"],
            "date_str": trigger_bar["date_str"],
            "close": trigger_bar["close"],
            "vix_at_trigger": vix_val,
        })
    return triggers


# ── Module 4 exit detection (EMA21 touch) ─────────────────────────────────────

def find_m4_exit(bars_4h, trigger_idx):
    """
    Module 4 exit: first bar where 4H high >= EMA21 after trigger.
    Scans up to 20 bars forward.
    """
    for j in range(trigger_idx + 1, min(trigger_idx + 20, len(bars_4h))):
        bar = bars_4h.iloc[j]
        ema21 = bar.get("ema_21")
        if pd.notna(ema21) and bar["high"] >= ema21:
            return {
                "exit_idx": j,
                "exit_ts": bar["timestamp"],
                "exit_date": bar["date_str"],
                "exit_close": bar["close"],
                "ema21_at_exit": ema21,
            }
    return None


# ── Handoff detection (4H gate flip to UP) ────────────────────────────────────

def find_handoff(bars_4h, exit_idx):
    """
    After Module 4 exit, scan next HANDOFF_SCAN_WINDOW 4H bars for
    EMA9 > EMA21 (gate flip to UP).
    """
    for j in range(exit_idx + 1, min(exit_idx + HANDOFF_SCAN_WINDOW + 1, len(bars_4h))):
        bar = bars_4h.iloc[j]
        ema9 = bar.get("ema_9")
        ema21 = bar.get("ema_21")
        if pd.notna(ema9) and pd.notna(ema21) and ema9 > ema21:
            return {
                "handoff_idx": j,
                "handoff_ts": bar["timestamp"],
                "handoff_date": bar["date_str"],
                "handoff_close": bar["close"],
                "bars_to_handoff": j - exit_idx,
            }
    return None


# ── Forward returns at 4H level ───────────────────────────────────────────────

def compute_4h_forward_returns(bars_4h, entry_idx, horizons):
    """Compute forward return % at each horizon from a 4H entry bar."""
    entry_close = bars_4h.iloc[entry_idx]["close"]
    result = {}
    for h in horizons:
        fwd_idx = entry_idx + h
        if fwd_idx < len(bars_4h):
            fwd_close = bars_4h.iloc[fwd_idx]["close"]
            result[h] = (fwd_close - entry_close) / entry_close * 100
        else:
            result[h] = np.nan
    return result


# ── Control group: regular 4H gate-UP bars ────────────────────────────────────

def collect_regular_gate_up_entries(bars_4h, m4_exit_indices):
    """
    Collect all 4H bars where EMA gate is UP (EMA9 > EMA21)
    that are NOT within 10 bars of a Module 4 exit.
    """
    blocked = set()
    for idx in m4_exit_indices:
        for j in range(max(0, idx - 2), min(len(bars_4h), idx + HANDOFF_SCAN_WINDOW + 1)):
            blocked.add(j)

    entries = []
    for i in range(1, len(bars_4h)):
        if i in blocked:
            continue
        bar = bars_4h.iloc[i]
        # Check PREVIOUS bar had gate UP (same logic as Module 2 pre-filter)
        prev = bars_4h.iloc[i - 1]
        ema9 = prev.get("ema_9")
        ema21 = prev.get("ema_21")
        if pd.notna(ema9) and pd.notna(ema21) and ema9 > ema21:
            entries.append(i)
    return entries


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_analysis():
    vix_daily = load_vix_daily()
    vix_series = load_vix_series()
    print(f"VIX data: {len(vix_daily)} trading days")

    # Accumulators
    all_triggers = []
    all_exits = []
    all_handoffs = []
    all_non_handoffs = []
    all_control_returns = []  # Regular gate-UP forward returns (control)

    for ticker in TICKERS:
        print(f"Processing {ticker}...")
        bars_4h = load_4h_bars(ticker)

        # Detect M4 triggers
        triggers = detect_m4_triggers(bars_4h, vix_daily)
        print(f"  {ticker}: {len(triggers)} M4 triggers")

        m4_exit_indices = []

        for trig in triggers:
            trig["ticker"] = ticker
            all_triggers.append(trig)

            # Find M4 exit
            exit_info = find_m4_exit(bars_4h, trig["idx"])
            if exit_info is None:
                continue

            exit_info["ticker"] = ticker
            exit_info["trigger_idx"] = trig["idx"]
            exit_info["trigger_vix"] = trig["vix_at_trigger"]
            m4_exit_indices.append(exit_info["exit_idx"])

            # VIX at M4 exit
            exit_info["vix_at_exit"] = get_vix_at_date(vix_series, exit_info["exit_date"])

            all_exits.append(exit_info)

            # Find handoff (gate flip UP)
            handoff = find_handoff(bars_4h, exit_info["exit_idx"])
            if handoff:
                handoff["ticker"] = ticker
                handoff["trigger_idx"] = trig["idx"]
                handoff["exit_idx"] = exit_info["exit_idx"]
                handoff["trigger_vix"] = trig["vix_at_trigger"]
                handoff["vix_at_exit"] = exit_info["vix_at_exit"]
                handoff["vix_at_handoff"] = get_vix_at_date(vix_series, handoff["handoff_date"])

                # Forward returns from handoff point
                fwd = compute_4h_forward_returns(bars_4h, handoff["handoff_idx"], FWD_HORIZONS)
                for h in FWD_HORIZONS:
                    handoff[f"fwd_{h}"] = fwd.get(h, np.nan)

                all_handoffs.append(handoff)
            else:
                all_non_handoffs.append(exit_info)

        # Control group: regular gate-UP entries (not near M4)
        control_indices = collect_regular_gate_up_entries(bars_4h, m4_exit_indices)
        for cidx in control_indices:
            fwd = compute_4h_forward_returns(bars_4h, cidx, FWD_HORIZONS)
            entry = {"ticker": ticker, "idx": cidx}
            for h in FWD_HORIZONS:
                entry[f"fwd_{h}"] = fwd.get(h, np.nan)
            all_control_returns.append(entry)

    print(f"\nTotal M4 triggers: {len(all_triggers)}")
    print(f"M4 exits (EMA21 touch): {len(all_exits)}")
    print(f"Handoffs (gate flip UP): {len(all_handoffs)}")
    print(f"Non-handoffs: {len(all_non_handoffs)}")
    print(f"Control group entries: {len(all_control_returns)}")

    return all_triggers, all_exits, all_handoffs, all_non_handoffs, all_control_returns


# ── Metrics ───────────────────────────────────────────────────────────────────

def metrics_from_returns(values):
    values = np.array([v for v in values if not np.isnan(v)])
    n = len(values)
    if n < 2:
        return {"N": n, "mean": np.nan, "median": np.nan, "wr": np.nan,
                "pf": np.nan, "std": np.nan, "p": np.nan}
    mean = np.mean(values)
    median = np.median(values)
    wr = np.sum(values > 0) / n * 100
    gains = np.sum(values[values > 0])
    losses = abs(np.sum(values[values < 0]))
    pf = gains / losses if losses > 0 else np.inf
    std = np.std(values)
    _, p = stats.ttest_1samp(values, 0)
    p = p / 2 if mean > 0 else 1 - p / 2
    return {"N": n, "mean": mean, "median": median, "wr": wr,
            "pf": pf, "std": std, "p": p}


def two_sample_test(vals_a, vals_b):
    a = np.array([v for v in vals_a if not np.isnan(v)])
    b = np.array([v for v in vals_b if not np.isnan(v)])
    if len(a) < 3 or len(b) < 3:
        return np.nan
    _, p = stats.ttest_ind(a, b, equal_var=False)
    return p


# ── Report ────────────────────────────────────────────────────────────────────

def generate_report(all_triggers, all_exits, all_handoffs, all_non_handoffs, all_control):
    lines = []
    lines.append("# S44 Module 2 — Part 3: Module 4 → Module 2 Handoff Analysis")
    lines.append("")
    lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Module 4 triggers:** {len(all_triggers)} (3 consecutive 4H down + VIX >= 25)")
    lines.append(f"**M4 exits (EMA21 touch):** {len(all_exits)}")
    lines.append(f"**Tickers:** {len(set(t['ticker'] for t in all_triggers))}/25")
    lines.append("")

    # ── Task A: Handoff Rate ──
    lines.append("## Task A: Handoff Rate")
    lines.append("")

    n_exits = len(all_exits)
    n_handoffs = len(all_handoffs)
    handoff_rate = n_handoffs / n_exits * 100 if n_exits > 0 else 0

    lines.append(f"**M4 exits:** {n_exits}")
    lines.append(f"**Handoffs (gate flip UP within {HANDOFF_SCAN_WINDOW} bars):** {n_handoffs}")
    lines.append(f"**Handoff rate:** {handoff_rate:.1f}%")
    lines.append(f"**Non-handoffs:** {len(all_non_handoffs)} ({100-handoff_rate:.1f}%)")
    lines.append("")

    if all_handoffs:
        bars_to = [h["bars_to_handoff"] for h in all_handoffs]
        lines.append(f"**Average time to handoff:** {np.mean(bars_to):.1f} 4H bars")
        lines.append(f"**Median time to handoff:** {np.median(bars_to):.1f} 4H bars")
        lines.append("")

        # Distribution
        lines.append("### Timing Distribution")
        lines.append("")
        lines.append("| Bars after M4 exit | Count | % of handoffs |")
        lines.append("|-------------------|-------|---------------|")

        from collections import Counter
        dist = Counter(bars_to)
        for b in sorted(dist.keys()):
            lines.append(f"| +{b} | {dist[b]} | {dist[b]/n_handoffs*100:.1f}% |")
        lines.append("")

    # ── Task B: Post-Handoff Returns ──
    lines.append("## Task B: Post-Handoff Returns vs Control")
    lines.append("")

    if not all_handoffs:
        lines.append("*No handoff events — cannot compute returns.*")
        lines.append("")
    else:
        # Handoff returns
        handoff_rets = {h: [ho[f"fwd_{h}"] for ho in all_handoffs] for h in FWD_HORIZONS}
        # Control returns (regular gate-UP, not post-M4)
        control_rets = {h: [c[f"fwd_{h}"] for c in all_control] for h in FWD_HORIZONS}

        lines.append("### Post-Handoff (entered at gate flip UP after M4 exit)")
        lines.append("")
        lines.append("| Horizon | N | Mean% | Median% | WR% | PF | p-val |")
        lines.append("|---------|---|-------|---------|-----|----|-------|")

        for h in FWD_HORIZONS:
            m = metrics_from_returns(handoff_rets[h])
            if np.isnan(m["mean"]):
                lines.append(f"| +{h} 4H | {m['N']} | — | — | — | — | — |")
                continue
            pf_str = f"{m['pf']:.2f}" if m['pf'] != np.inf else "inf"
            sig = "***" if m['p'] < 0.001 else ("**" if m['p'] < 0.01 else ("*" if m['p'] < 0.05 else ""))
            lines.append(
                f"| +{h} 4H | {m['N']} | {m['mean']:+.3f} | {m['median']:+.3f} | "
                f"{m['wr']:.1f} | {pf_str} | {m['p']:.4f}{sig} |"
            )
        lines.append("")

        lines.append("### Control Group (regular gate-UP, NOT post-M4)")
        lines.append("")
        lines.append("| Horizon | N | Mean% | Median% | WR% | PF | p-val |")
        lines.append("|---------|---|-------|---------|-----|----|-------|")

        for h in FWD_HORIZONS:
            m = metrics_from_returns(control_rets[h])
            if np.isnan(m["mean"]):
                lines.append(f"| +{h} 4H | {m['N']} | — | — | — | — | — |")
                continue
            pf_str = f"{m['pf']:.2f}" if m['pf'] != np.inf else "inf"
            sig = "***" if m['p'] < 0.001 else ("**" if m['p'] < 0.01 else ("*" if m['p'] < 0.05 else ""))
            lines.append(
                f"| +{h} 4H | {m['N']} | {m['mean']:+.3f} | {m['median']:+.3f} | "
                f"{m['wr']:.1f} | {pf_str} | {m['p']:.4f}{sig} |"
            )
        lines.append("")

        # Comparison
        lines.append("### Handoff vs Control Separation")
        lines.append("")
        lines.append("| Horizon | Handoff Mean% | Control Mean% | Delta% | Sep p-val | Significant? |")
        lines.append("|---------|--------------|--------------|--------|-----------|--------------|")

        for h in FWD_HORIZONS:
            h_m = metrics_from_returns(handoff_rets[h])
            c_m = metrics_from_returns(control_rets[h])
            if np.isnan(h_m["mean"]) or np.isnan(c_m["mean"]):
                lines.append(f"| +{h} 4H | — | — | — | — | — |")
                continue
            delta = h_m["mean"] - c_m["mean"]
            sep_p = two_sample_test(handoff_rets[h], control_rets[h])
            is_sig = "YES" if (not np.isnan(sep_p) and sep_p < 0.05) else "no"
            sep_p_str = f"{sep_p:.4f}" if not np.isnan(sep_p) else "—"
            lines.append(
                f"| +{h} 4H | {h_m['mean']:+.3f} | {c_m['mean']:+.3f} | "
                f"{delta:+.3f} | {sep_p_str} | {is_sig} |"
            )
        lines.append("")

    # ── Task C: VIX Transition ──
    lines.append("## Task C: VIX Transition Analysis")
    lines.append("")

    if all_handoffs:
        # VIX at trigger, exit, handoff
        vix_at_trigger = [h["trigger_vix"] for h in all_handoffs
                         if h["trigger_vix"] is not None and not np.isnan(h["trigger_vix"])]
        vix_at_exit = [h["vix_at_exit"] for h in all_handoffs
                       if h["vix_at_exit"] is not None and not np.isnan(h["vix_at_exit"])]
        vix_at_handoff = [h["vix_at_handoff"] for h in all_handoffs
                          if h["vix_at_handoff"] is not None and not np.isnan(h["vix_at_handoff"])]

        lines.append("### VIX Levels Through Transition")
        lines.append("")
        lines.append("| Stage | N | Mean VIX | Median VIX | Min | Max |")
        lines.append("|-------|---|----------|------------|-----|-----|")
        for label, vals in [("M4 Trigger", vix_at_trigger), ("M4 Exit", vix_at_exit), ("M2 Handoff", vix_at_handoff)]:
            if vals:
                lines.append(
                    f"| {label} | {len(vals)} | {np.mean(vals):.1f} | {np.median(vals):.1f} | "
                    f"{np.min(vals):.1f} | {np.max(vals):.1f} |"
                )
            else:
                lines.append(f"| {label} | 0 | — | — | — | — |")
        lines.append("")

        # VIX < 25 at handoff?
        handoff_vix_below_25 = [h for h in all_handoffs if h["vix_at_handoff"] is not None and h["vix_at_handoff"] < 25]
        handoff_vix_above_25 = [h for h in all_handoffs if h["vix_at_handoff"] is not None and h["vix_at_handoff"] >= 25]

        n_below = len(handoff_vix_below_25)
        n_above = len(handoff_vix_above_25)
        lines.append(f"**VIX < 25 at handoff:** {n_below} ({n_below/(n_below+n_above)*100:.1f}%)" if n_below + n_above > 0 else "")
        lines.append(f"**VIX >= 25 at handoff:** {n_above} ({n_above/(n_below+n_above)*100:.1f}%)" if n_below + n_above > 0 else "")
        lines.append("")

        # Does VIX < 25 at handoff predict better returns?
        if n_below >= 3 and n_above >= 3:
            lines.append("### VIX < 25 vs VIX >= 25 at Handoff — Forward Returns")
            lines.append("")
            lines.append("| Horizon | VIX<25 Mean% | VIX<25 N | VIX>=25 Mean% | VIX>=25 N | Delta | p-val |")
            lines.append("|---------|-------------|----------|--------------|-----------|-------|-------|")

            for h in FWD_HORIZONS:
                below_vals = [ho[f"fwd_{h}"] for ho in handoff_vix_below_25]
                above_vals = [ho[f"fwd_{h}"] for ho in handoff_vix_above_25]
                m_below = metrics_from_returns(below_vals)
                m_above = metrics_from_returns(above_vals)

                if not np.isnan(m_below["mean"]) and not np.isnan(m_above["mean"]):
                    delta = m_below["mean"] - m_above["mean"]
                    sep_p = two_sample_test(below_vals, above_vals)
                    sep_p_str = f"{sep_p:.4f}" if not np.isnan(sep_p) else "—"
                    lines.append(
                        f"| +{h} 4H | {m_below['mean']:+.3f} | {m_below['N']} | "
                        f"{m_above['mean']:+.3f} | {m_above['N']} | "
                        f"{delta:+.3f} | {sep_p_str} |"
                    )
                else:
                    lines.append(f"| +{h} 4H | — | — | — | — | — | — |")
            lines.append("")
        elif n_below + n_above > 0:
            lines.append("*Insufficient data to split by VIX at handoff (one group < 3 trades).*")
            lines.append("")
    else:
        lines.append("*No handoff events — cannot analyze VIX transition.*")
        lines.append("")

    # ── Verdict ──
    lines.append("## Verdict")
    lines.append("")

    if not all_handoffs:
        lines.append("**No handoff events detected.** Module 4 exits do not lead to 4H uptrends within 10 bars.")
        lines.append("")
    else:
        # Assess based on separation test at +3 4H bars (medium horizon)
        test_horizon = 3
        h_rets = [ho[f"fwd_{test_horizon}"] for ho in all_handoffs]
        c_rets = [c[f"fwd_{test_horizon}"] for c in all_control]
        h_m = metrics_from_returns(h_rets)
        c_m = metrics_from_returns(c_rets)
        sep_p = two_sample_test(h_rets, c_rets)

        if not np.isnan(h_m["mean"]) and not np.isnan(c_m["mean"]):
            delta = h_m["mean"] - c_m["mean"]
            sig = not np.isnan(sep_p) and sep_p < 0.05

            if sig and delta > 0:
                lines.append("**Module 4→2 handoff = SYSTEMATIC EDGE → implement as linked trade.**")
                lines.append("")
                lines.append(f"Post-handoff returns are significantly better than regular Module 2:")
                lines.append(f"- Handoff: {h_m['mean']:+.3f}% at +{test_horizon} 4H bars (N={h_m['N']})")
                lines.append(f"- Control: {c_m['mean']:+.3f}% (N={c_m['N']})")
                lines.append(f"- Delta: {delta:+.3f}% (p={sep_p:.4f})")
                lines.append("")
                lines.append("### Proposed Implementation")
                lines.append("")
                lines.append("```")
                lines.append("TRIGGER:   Module 4 exit (4H high >= EMA21)")
                lines.append("WATCH:     Monitor for 4H EMA9 > EMA21 flip (up to 10 bars)")
                lines.append("ENTRY:     Enter LONG at 4H bar close where gate flips UP")
                lines.append("EXIT:      Hold for +3 to +5 4H bars (or until gate flips DOWN)")
                lines.append("STOP:      -1.5% from entry")
                lines.append("```")
            elif sig and delta < 0:
                lines.append("**Module 4→2 handoff = WEAKER than regular Module 2 → avoid.**")
                lines.append("")
                lines.append(f"Post-handoff returns are significantly worse:")
                lines.append(f"- Handoff: {h_m['mean']:+.3f}% vs Control: {c_m['mean']:+.3f}%")
                lines.append(f"- Delta: {delta:+.3f}% (p={sep_p:.4f})")
                lines.append("The MR bounce may exhaust momentum, weakening subsequent trend.")
            else:
                lines.append("**Module 4→2 handoff = SAME as regular Module 2 → no special treatment needed.**")
                lines.append("")
                lines.append(f"Post-handoff returns are not significantly different from control:")
                lines.append(f"- Handoff: {h_m['mean']:+.3f}% at +{test_horizon} 4H bars (N={h_m['N']})")
                lines.append(f"- Control: {c_m['mean']:+.3f}% (N={c_m['N']})")
                lines.append(f"- Delta: {delta:+.3f}% (p={sep_p:.4f})")
                lines.append("")
                lines.append("Module 4 exits that transition into uptrends are just regular Module 2 territory.")
                lines.append("No linked-trade mechanism needed — standard Module 2 rules apply.")
        else:
            lines.append("**Insufficient data for verdict.**")

    lines.append("")

    # ── Summary stats ──
    lines.append("## Summary Statistics")
    lines.append("")
    lines.append(f"- M4 triggers: {len(all_triggers)}")
    lines.append(f"- M4 exits: {len(all_exits)}")
    lines.append(f"- Handoffs: {len(all_handoffs)} ({handoff_rate:.1f}%)")
    lines.append(f"- Control group: {len(all_control)} regular gate-UP bars")
    lines.append(f"- Handoff scan window: {HANDOFF_SCAN_WINDOW} 4H bars")
    lines.append(f"- Forward horizons: {', '.join(f'+{h} 4H' for h in FWD_HORIZONS)}")
    lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    triggers, exits, handoffs, non_handoffs, control = run_analysis()
    report = generate_report(triggers, exits, handoffs, non_handoffs, control)

    output_path = RESULTS_DIR / "S44_Module2_Part3_Handoff_Results.md"
    output_path.write_text(report)
    print(f"\nResults saved to {output_path}")
    print("\n" + report)
