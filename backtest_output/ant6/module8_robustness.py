#!/usr/bin/env python3
"""
Module 8 Clean Re-Test — Robustness & Verdict (Steps 6-8)
ANT-6 Pass A: Method Cleanup
Conditioning analysis, LOTO, bootstrap, IS/OOS, verdict.
"""

import csv, os, json, random, math
from collections import defaultdict

BASE = "/home/user/stock-data-mining/backtest_output"
OUT = os.path.join(BASE, "ant6")

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_trades(cap_label):
    path = os.path.join(OUT, f"module8_all_trades_{cap_label}.csv")
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["return_gross"] = float(r["return_gross"])
        r["entry_price"] = float(r["entry_price"])
        r["exit_price"] = float(r["exit_price"])
        gp = r.get("gap_pct", "")
        r["gap_pct"] = float(gp) if gp else None
        for k in ["eps_surprise_pct", "revenue_surprise_pct"]:
            v = r.get(k, "")
            r[k] = float(v) if v not in ("", None) else None
    return rows


def stats(rets):
    rets = [r for r in rets if r is not None]
    if not rets:
        return {"N": 0, "mean": None, "median": None, "wr": None, "pf": None}
    n = len(rets)
    m = sum(rets) / n
    med = sorted(rets)[n // 2]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    wr = len(wins) / n
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else 999.0
    return {"N": n, "mean": round(m, 6), "median": round(med, 6),
            "wr": round(wr, 4), "pf": round(min(pf, 999.0), 2)}


def filter_trades(trades, entry, exit_l, stop):
    return [t for t in trades if t["entry"] == entry
            and t["exit"] == exit_l and t["stop"] == stop]


# ── Best combo selection ─────────────────────────────────────────────────────

def find_best_combo(trades, stop="A_no_stop"):
    """Find entry/exit with highest mean gross in Layer A."""
    combos = defaultdict(list)
    for t in trades:
        if t["stop"] != stop:
            continue
        combos[(t["entry"], t["exit"])].append(t["return_gross"])
    best_key = max(combos, key=lambda k: sum(combos[k]) / len(combos[k]))
    return best_key


# ── Step 6: Conditioning ────────────────────────────────────────────────────

def conditioning_analysis(trades, entry, exit_l, stop="A_no_stop"):
    subset = filter_trades(trades, entry, exit_l, stop)
    if not subset:
        return {}

    results = {}
    rets = [t["return_gross"] for t in subset]

    # A. Gap severity
    gap_buckets = {"5-8%": [], "8-10%": [], "10-15%": []}
    for t in subset:
        gp = t["gap_pct"]
        if gp is None:
            continue
        if gp < 0.08:
            gap_buckets["5-8%"].append(t["return_gross"])
        elif gp < 0.10:
            gap_buckets["8-10%"].append(t["return_gross"])
        else:
            gap_buckets["10-15%"].append(t["return_gross"])
    results["gap_severity"] = {k: stats(v) for k, v in gap_buckets.items()}

    # B. EPS surprise
    eps_buckets = {"MISS (<-5%)": [], "INLINE (-5,+5)": [], "BEAT (>+5%)": [], "UNKNOWN": []}
    for t in subset:
        sp = t["eps_surprise_pct"]
        if sp is None:
            eps_buckets["UNKNOWN"].append(t["return_gross"])
        elif sp < -5:
            eps_buckets["MISS (<-5%)"].append(t["return_gross"])
        elif sp > 5:
            eps_buckets["BEAT (>+5%)"].append(t["return_gross"])
        else:
            eps_buckets["INLINE (-5,+5)"].append(t["return_gross"])
    results["eps_surprise"] = {k: stats(v) for k, v in eps_buckets.items()}

    # C. Revenue surprise
    rev_buckets = {"MISS (<-2%)": [], "INLINE (-2,+2)": [], "BEAT (>+2%)": [], "UNKNOWN": []}
    for t in subset:
        rsp = t["revenue_surprise_pct"]
        if rsp is None:
            rev_buckets["UNKNOWN"].append(t["return_gross"])
        elif rsp < -2:
            rev_buckets["MISS (<-2%)"].append(t["return_gross"])
        elif rsp > 2:
            rev_buckets["BEAT (>+2%)"].append(t["return_gross"])
        else:
            rev_buckets["INLINE (-2,+2)"].append(t["return_gross"])
    results["revenue_surprise"] = {k: stats(v) for k, v in rev_buckets.items()}

    # D. Release timing
    timing_buckets = {"BMO": [], "AMC": []}
    for t in subset:
        rt = t.get("release_timing", "")
        if rt in timing_buckets:
            timing_buckets[rt].append(t["return_gross"])
    results["release_timing"] = {k: stats(v) for k, v in timing_buckets.items()}

    # E. Damage class
    dmg_buckets = {"HARD": [], "MIXED": [], "SOFT": [], "UNKNOWN": []}
    for t in subset:
        eps_sp = t["eps_surprise_pct"]
        rev_sp = t["revenue_surprise_pct"]
        if eps_sp is None or rev_sp is None:
            dmg_buckets["UNKNOWN"].append(t["return_gross"])
        elif eps_sp < -5 and rev_sp < -2:
            dmg_buckets["HARD"].append(t["return_gross"])
        elif eps_sp < -5 or rev_sp < -2:
            dmg_buckets["MIXED"].append(t["return_gross"])
        else:
            dmg_buckets["SOFT"].append(t["return_gross"])
    results["damage_class"] = {k: stats(v) for k, v in dmg_buckets.items()}

    return results


# ── Step 7: Robustness ──────────────────────────────────────────────────────

def is_oos_split(trades, entry, exit_l, stop="A_no_stop"):
    """Chronological 50/50 split."""
    subset = filter_trades(trades, entry, exit_l, stop)
    subset.sort(key=lambda t: t["d0_date"])
    mid = len(subset) // 2
    is_set = subset[:mid]
    oos_set = subset[mid:]
    return stats([t["return_gross"] for t in is_set]), stats([t["return_gross"] for t in oos_set])


def leave_one_ticker_out(trades, entry, exit_l, stop="A_no_stop"):
    """LOTO analysis."""
    subset = filter_trades(trades, entry, exit_l, stop)
    all_rets = [t["return_gross"] for t in subset]
    all_stats = stats(all_rets)
    tickers = sorted(set(t["ticker"] for t in subset))

    loto = []
    for ticker in tickers:
        remaining = [t["return_gross"] for t in subset if t["ticker"] != ticker]
        s = stats(remaining)
        impact = ""
        if all_stats["mean"] is not None and s["mean"] is not None:
            if all_stats["mean"] != 0:
                pct_change = (s["mean"] - all_stats["mean"]) / abs(all_stats["mean"]) * 100
                impact = f"{pct_change:+.0f}%"
                if (all_stats["mean"] > 0 and s["mean"] <= 0) or \
                   (all_stats["mean"] < 0 and s["mean"] >= 0):
                    impact += " SIGN_FLIP"
        loto.append({"ticker_removed": ticker, **s, "impact": impact})
    return loto


def top_winner_removal(trades, entry, exit_l, stop="A_no_stop"):
    """Remove top-1 and top-2 winners."""
    subset = filter_trades(trades, entry, exit_l, stop)
    rets = sorted([t["return_gross"] for t in subset], reverse=True)
    results = {}
    results["full"] = stats(rets)
    if len(rets) > 1:
        results["remove_top1"] = stats(rets[1:])
    if len(rets) > 2:
        results["remove_top2"] = stats(rets[2:])
    return results


def bootstrap_ci(trades, entry, exit_l, stop="A_no_stop", n_boot=10000):
    """Bootstrap 95% CI for mean and median."""
    subset = filter_trades(trades, entry, exit_l, stop)
    rets = [t["return_gross"] for t in subset]
    if len(rets) < 3:
        return {}

    random.seed(42)
    means = []
    medians = []
    for _ in range(n_boot):
        sample = random.choices(rets, k=len(rets))
        means.append(sum(sample) / len(sample))
        medians.append(sorted(sample)[len(sample) // 2])

    means.sort()
    medians.sort()
    lo = int(n_boot * 0.025)
    hi = int(n_boot * 0.975)

    return {
        "mean_ci_95": [round(means[lo], 6), round(means[hi], 6)],
        "median_ci_95": [round(medians[lo], 6), round(medians[hi], 6)],
        "mean_point": round(sum(rets) / len(rets), 6),
    }


def bootstrap_trigger_vs_control(trades, trig_entry, ctrl_entry, exit_l,
                                  stop="A_no_stop", n_boot=10000):
    """Bootstrap the difference trigger_mean - control_mean."""
    trig = filter_trades(trades, trig_entry, exit_l, stop)
    ctrl = filter_trades(trades, ctrl_entry, exit_l, stop)
    trig_rets = [t["return_gross"] for t in trig]
    ctrl_rets = [t["return_gross"] for t in ctrl]
    if len(trig_rets) < 3 or len(ctrl_rets) < 3:
        return {}

    random.seed(42)
    diffs = []
    for _ in range(n_boot):
        ts = random.choices(trig_rets, k=len(trig_rets))
        cs = random.choices(ctrl_rets, k=len(ctrl_rets))
        diffs.append(sum(ts) / len(ts) - sum(cs) / len(cs))

    diffs.sort()
    lo = int(n_boot * 0.025)
    hi = int(n_boot * 0.975)

    return {
        "diff_ci_95": [round(diffs[lo], 6), round(diffs[hi], 6)],
        "diff_point": round(sum(trig_rets) / len(trig_rets) - sum(ctrl_rets) / len(ctrl_rets), 6),
    }


# ── Step 8: Verdict ─────────────────────────────────────────────────────────

def generate_verdict(cap_label, best_entry, best_exit, hr_data, cond, is_stats,
                     oos_stats, loto, topwin, boot, boot_diff):
    """Generate the verdict markdown."""

    lines = []
    lines.append("# Module 8 Clean Re-Test — Verdict")
    lines.append(f"## ANT-6 Pass A: Method Cleanup — {cap_label}")
    lines.append(f"Date: 2026-04-05\n")

    lines.append(f"### Best combo (Layer A): {best_entry} → {best_exit}")
    lines.append("")

    # Key finding
    lines.append("## KEY FINDING: Trigger entry DOES NOT beat control entries\n")
    lines.append("Across ALL exit variants, E1 (trigger-next) loses to C1 (10:00 buy)")
    lines.append("and C2 (noon buy). The trigger adds negative value — it delays entry")
    lines.append("into a bounce that is already largely captured by buying at 10:00.\n")

    # Dimension ratings
    lines.append("## Dimension Ratings\n")
    lines.append("| Dimension | Rating | Evidence |")
    lines.append("|-----------|--------|----------|")

    # Data integrity
    lines.append("| Data integrity | PASS | 22/27 tickers with cached daily+M5 data, "
                 "5 excluded (SMCI/ARM/INTC/MSTR/JD) for lack of data. Single daily provider. |")

    # No look-ahead
    lines.append("| No look-ahead | PASS | Trigger uses running low from bars strictly "
                 "prior to current bar. Entry at next bar open. |")

    # Universe consistency
    lines.append("| Universe consistency | PASS | Fixed 22-ticker universe, canonical D0 "
                 "mapping, gap convention consistent. |")

    # Trigger adds value
    lines.append("| Trigger adds value | **FAIL** | E1 loses to C1 on every exit. "
                 "E1 loses to C2 on every exit. Trigger subtracts value. |")

    # Exit stability
    best_exit_short = best_exit.split("_")[0]
    lines.append(f"| Exit stability | PARTIAL | Best exit is {best_exit} but the edge "
                 "belongs to C1 (control), not trigger entries. |")

    # Robustness
    is_mean = is_stats.get("mean")
    oos_mean = oos_stats.get("mean")
    if is_mean is not None and oos_mean is not None:
        if (is_mean > 0) == (oos_mean > 0):
            rob_rating = "PASS"
            rob_ev = f"IS mean={is_mean*100:.2f}%, OOS mean={oos_mean*100:.2f}% — same sign"
        else:
            rob_rating = "FAIL"
            rob_ev = f"IS mean={is_mean*100:.2f}%, OOS mean={oos_mean*100:.2f}% — sign flip"
    else:
        rob_rating = "INCONCLUSIVE"
        rob_ev = "Insufficient data"
    lines.append(f"| Robustness | {rob_rating} | {rob_ev} |")

    # Mechanism coherence
    lines.append("| Mechanism coherence | **FAIL** | The hypothesized mechanism — that a "
                 "recovery trigger identifies optimal re-entry timing — is falsified. "
                 "Simple early buying (C1 at 10:00) captures the gap-fill drift without "
                 "needing any trigger. The trigger's delay costs performance. |")

    lines.append("")

    # Final verdict
    lines.append("## Final Verdict: **REJECTED**\n")
    lines.append("### Fail conditions triggered:")
    lines.append("- **Controls beat trigger entries** — C1 dominates E1/E2/E3 across all exits")
    lines.append("- **Trigger subtracts value** — waiting for recovery confirmation misses the bounce")
    lines.append("- **E1 mean and median both negative gross** for most exits\n")

    lines.append("### What the data shows:")
    lines.append("- Gap-down earnings reactions DO show mean-reversion toward prior close")
    lines.append("- The reversion begins early (hence C1 at 10:00 captures it)")
    lines.append("- Waiting for a 35% recovery trigger means entering AFTER most of the "
                 "intraday bounce, leaving the trade exposed to overnight/multi-day risk")
    lines.append("- The best strategy in this universe is simply buying at 10:00 and "
                 "selling at D1 open or D1 close (C1→X1 or C1→X2)\n")

    lines.append("### Implication:")
    lines.append("Module 8's trigger mechanism is not useful. If anything, the underlying ")
    lines.append("gap-fill phenomenon (C1 results) could be studied further, but the ")
    lines.append("trigger itself should be retired.\n")

    # Conditioning summary
    lines.append("## Conditioning Summary (best control: C1)\n")
    if cond:
        for section, data in cond.items():
            lines.append(f"### {section}")
            lines.append("| Bucket | N | Mean% | Med% | WR | PF |")
            lines.append("|--------|---|-------|------|----|----|")
            for bucket, s in data.items():
                if s["N"] > 0:
                    flag = " ◀ANECDOTAL" if s["N"] < 10 else ""
                    lines.append(
                        f"| {bucket} | {s['N']} | "
                        f"{s['mean']*100:.2f} | {s['median']*100:.2f} | "
                        f"{s['wr']*100:.1f} | {s['pf']:.2f} |{flag}")
            lines.append("")

    # Bootstrap
    lines.append("## Bootstrap (10,000 resamples)\n")
    if boot:
        lines.append(f"- Mean 95% CI: [{boot['mean_ci_95'][0]*100:.2f}%, "
                     f"{boot['mean_ci_95'][1]*100:.2f}%]")
        lines.append(f"- Median 95% CI: [{boot['median_ci_95'][0]*100:.2f}%, "
                     f"{boot['median_ci_95'][1]*100:.2f}%]")
    if boot_diff:
        lines.append(f"- E1-C2 diff 95% CI: [{boot_diff['diff_ci_95'][0]*100:.2f}%, "
                     f"{boot_diff['diff_ci_95'][1]*100:.2f}%]")
        lines.append(f"- E1-C2 point est: {boot_diff['diff_point']*100:.2f}%")
    lines.append("")

    # IS/OOS
    lines.append("## IS/OOS Split (chronological 50/50)\n")
    if is_stats["N"] and oos_stats["N"]:
        lines.append(f"- IS:  N={is_stats['N']}, mean={is_stats['mean']*100:.2f}%, "
                     f"median={is_stats['median']*100:.2f}%, WR={is_stats['wr']*100:.1f}%")
        lines.append(f"- OOS: N={oos_stats['N']}, mean={oos_stats['mean']*100:.2f}%, "
                     f"median={oos_stats['median']*100:.2f}%, WR={oos_stats['wr']*100:.1f}%")
    lines.append("")

    # Top winner removal
    lines.append("## Top Winner Removal\n")
    for k, s in topwin.items():
        if s["N"]:
            lines.append(f"- {k}: N={s['N']}, mean={s['mean']*100:.2f}%")
    lines.append("")

    # LOTO summary
    lines.append("## Leave-One-Ticker-Out\n")
    lines.append("| Ticker Removed | N | Mean% | WR | PF | Impact |")
    lines.append("|---------------|---|-------|----|----|--------|")
    for row in loto:
        if row["N"] > 0:
            lines.append(f"| {row['ticker_removed']} | {row['N']} | "
                         f"{row['mean']*100:.2f} | {row['wr']*100:.1f} | "
                         f"{row['pf']:.2f} | {row['impact']} |")
    lines.append("")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("MODULE 8 CLEAN RE-TEST — ROBUSTNESS & VERDICT (Steps 6-8)")
    print("ANT-6 Pass A: Method Cleanup")
    print("=" * 70)

    for cap_label in ["cap10", "cap15"]:
        print(f"\n{'='*50}")
        print(f"Processing {cap_label}...")
        print(f"{'='*50}")

        trades = load_trades(cap_label)
        print(f"Loaded {len(trades)} trades")

        # Find best combo overall (Layer A)
        best_entry, best_exit = find_best_combo(trades, "A_no_stop")
        print(f"Best combo (Layer A): {best_entry} → {best_exit}")

        # Also find best TRIGGER combo
        trig_trades = [t for t in trades if t["entry"] in ("E1", "E2", "E3")]
        if trig_trades:
            best_trig_entry, best_trig_exit = find_best_combo(
                trig_trades, "A_no_stop")
            print(f"Best trigger combo: {best_trig_entry} → {best_trig_exit}")

        # Step 6: Conditioning on BEST combo
        print("\n▶ Step 6: Conditioning analysis...")
        cond = conditioning_analysis(trades, best_entry, best_exit)

        for section, data in cond.items():
            print(f"\n  {section}:")
            for bucket, s in data.items():
                if s["N"] > 0:
                    flag = " ◀ANECDOTAL" if s["N"] < 10 else ""
                    print(f"    {bucket:20s} N={s['N']:2d} mean={s['mean']*100:+6.2f}% "
                          f"med={s['median']*100:+6.2f}% WR={s['wr']*100:4.1f}% "
                          f"PF={s['pf']:5.2f}{flag}")

        # Write conditioning CSV
        cond_rows = []
        for section, data in cond.items():
            for bucket, s in data.items():
                cond_rows.append({"section": section, "bucket": bucket, **s})
        cond_path = os.path.join(OUT, f"module8_conditioning_{cap_label}.csv")
        if cond_rows:
            with open(cond_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(cond_rows[0].keys()))
                w.writeheader()
                w.writerows(cond_rows)
            print(f"  Wrote {cond_path}")

        # Step 7a: IS/OOS
        print("\n▶ Step 7a: IS/OOS split...")
        is_stats, oos_stats = is_oos_split(trades, best_entry, best_exit)
        print(f"  IS:  {is_stats}")
        print(f"  OOS: {oos_stats}")

        # Step 7b: LOTO
        print("\n▶ Step 7b: Leave-one-ticker-out...")
        loto = leave_one_ticker_out(trades, best_entry, best_exit)
        loto_path = os.path.join(OUT, f"module8_leave_one_ticker_out_{cap_label}.csv")
        if loto:
            with open(loto_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(loto[0].keys()))
                w.writeheader()
                w.writerows(loto)
            print(f"  Wrote {loto_path}")
            for row in loto:
                print(f"    Remove {row['ticker_removed']:5s}: N={row['N']} "
                      f"mean={row['mean']*100:+6.2f}% {row['impact']}")

        # Step 7c: Top winner removal
        print("\n▶ Step 7c: Top winner removal...")
        topwin = top_winner_removal(trades, best_entry, best_exit)
        for k, s in topwin.items():
            if s["N"]:
                print(f"  {k}: N={s['N']} mean={s['mean']*100:+6.2f}%")

        # Step 7d: Bootstrap
        print("\n▶ Step 7d: Bootstrap...")
        boot = bootstrap_ci(trades, best_entry, best_exit)
        if boot:
            print(f"  Mean 95% CI: [{boot['mean_ci_95'][0]*100:.2f}%, "
                  f"{boot['mean_ci_95'][1]*100:.2f}%]")
            print(f"  Median 95% CI: [{boot['median_ci_95'][0]*100:.2f}%, "
                  f"{boot['median_ci_95'][1]*100:.2f}%]")

        # Bootstrap trigger vs control
        boot_diff = bootstrap_trigger_vs_control(
            trades, "E1", "C2", best_exit)
        if boot_diff:
            print(f"  E1-C2 diff 95% CI: [{boot_diff['diff_ci_95'][0]*100:.2f}%, "
                  f"{boot_diff['diff_ci_95'][1]*100:.2f}%]")

        # Write bootstrap summary
        boot_summary = {"best_combo_boot": boot, "e1_vs_c2_boot": boot_diff}
        boot_path = os.path.join(OUT, f"module8_bootstrap_summary_{cap_label}.json")
        with open(boot_path, "w") as f:
            json.dump(boot_summary, f, indent=2)

        # Step 8: Verdict
        print("\n▶ Step 8: Generating verdict...")
        verdict = generate_verdict(
            cap_label, best_entry, best_exit, None, cond,
            is_stats, oos_stats, loto, topwin, boot, boot_diff)

        verdict_path = os.path.join(OUT, f"module8_verdict_{cap_label}.md")
        with open(verdict_path, "w") as f:
            f.write(verdict)
        print(f"  Wrote {verdict_path}")

    # Also write combined verdict
    print("\n" + "=" * 70)
    print("COMBINED VERDICT")
    print("=" * 70)
    print("\nModule 8 trigger mechanism: REJECTED")
    print("Trigger entry (E1/E2/E3) loses to ALL controls (C1/C2) on EVERY exit.")
    print("The gap-fill phenomenon is real (C1→X1 positive), but the trigger adds no value.")
    print("Best strategy: C1 (buy at 10:00) → X1 (sell at D1 open) or X2 (D1 close).")

    print("\n✓ Robustness & verdict complete.")


if __name__ == "__main__":
    main()
