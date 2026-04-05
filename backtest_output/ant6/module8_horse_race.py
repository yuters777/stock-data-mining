#!/usr/bin/env python3
"""
Module 8 Clean Re-Test — Horse Race (Steps 2-5)
ANT-6 Pass A: Method Cleanup
Entry variants, exit variants, stop overlay, horse race table.
"""

import csv, os, json, math
from datetime import datetime
from collections import defaultdict

BASE = "/home/user/stock-data-mining/backtest_output"
OUT = os.path.join(BASE, "ant6")

# ── Load helpers ─────────────────────────────────────────────────────────────

def load_trigger_csv(cap_label):
    path = os.path.join(OUT, f"module8_trigger_events_{cap_label}.csv")
    with open(path) as f:
        rows = list(csv.DictReader(f))
    # Convert numeric fields
    for r in rows:
        for k in ["gap_pct","gap_abs","prev_close","d0_open","d0_close",
                   "trigger_recovery_ratio","trigger_running_low",
                   "overshoot_ratio","entry_price","initial_stop",
                   "d1_open","d1_close","d2_close","d3_close","d5_close",
                   "bar_10_00_open","bar_12_00_open"]:
            v = r.get(k, "")
            r[k] = float(v) if v != "" else None
        r["trigger_fired"] = r["trigger_fired"] == "True"
        r["d0_m5_count"] = int(r.get("d0_m5_count", 0))
    return rows


def load_m5(ticker):
    path = os.path.join(BASE, f"{ticker}_m5_regsess.csv")
    if not os.path.exists(path):
        return []
    bars = []
    with open(path) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            bars.append({
                "dt": dt, "date": dt.strftime("%Y-%m-%d"),
                "time": dt.strftime("%H:%M"),
                "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]), "close": float(row["Close"]),
                "volume": int(float(row["Volume"])),
            })
    bars.sort(key=lambda x: x["dt"])
    return bars


def load_daily(ticker):
    path = os.path.join(BASE, f"{ticker}_daily.csv")
    if not os.path.exists(path):
        return {}
    daily = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            daily[row["date"]] = {
                "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]), "close": float(row["Close"]),
            }
    return daily


# ── Step 2: Entry Variants ──────────────────────────────────────────────────

def compute_entries(ev, d0_m5_bars):
    """
    Returns dict of entry_label -> entry_price (or None).
    Also returns confirmation bar details for E2.
    """
    entries = {}
    triggered = ev["trigger_fired"]

    # Control entries — on ALL eligible gap-down events
    entries["C1"] = ev["bar_10_00_open"]  # Buy at 10:00 open
    entries["C2"] = ev["bar_12_00_open"]  # Buy at 12:00 open

    if not triggered:
        entries["C3"] = None  # C3 only for triggered events
        entries["E1"] = None
        entries["E2"] = None
        entries["E3"] = None
        return entries

    # C3 — 12:00 open but only for triggered events
    entries["C3"] = ev["bar_12_00_open"]

    # E1 — TriggerNext (canonical): next bar open after trigger
    entries["E1"] = ev["entry_price"]

    # E2 — TriggerConfirm: require one extra bar with no new low + close > trigger close
    trigger_bar_idx = ev.get("trigger_bar_idx", "")
    if trigger_bar_idx != "" and trigger_bar_idx is not None:
        tbi = int(float(trigger_bar_idx))
        trigger_bar = d0_m5_bars[tbi] if tbi < len(d0_m5_bars) else None
        running_low = ev["trigger_running_low"]

        if trigger_bar and tbi + 1 < len(d0_m5_bars):
            confirm_bar = d0_m5_bars[tbi + 1]
            # Confirmation: no new low AND close > trigger bar close
            if (running_low is not None and
                confirm_bar["low"] >= running_low and
                confirm_bar["close"] > trigger_bar["close"]):
                # Entry = bar AFTER confirmation bar
                if tbi + 2 < len(d0_m5_bars):
                    entries["E2"] = d0_m5_bars[tbi + 2]["open"]
                else:
                    entries["E2"] = None
            else:
                entries["E2"] = None
        else:
            entries["E2"] = None
    else:
        entries["E2"] = None

    # E3 — NoonQualified: if trigger fires by 11:55, enter at 12:00 open
    trig_time = ev["trigger_time_et"]
    if trig_time and trig_time <= "11:55":
        entries["E3"] = ev["bar_12_00_open"]
    else:
        entries["E3"] = None

    return entries


# ── Step 3: Exit Variants ───────────────────────────────────────────────────

def compute_exits(ev):
    """Returns dict of exit_label -> exit_price (or None)."""
    return {
        "X0_D0_close": ev["d0_close"],
        "X1_D1_open":  ev["d1_open"],
        "X2_D1_close": ev["d1_close"],
        "X3_D2_close": ev["d2_close"],
        "X4_D3_close": ev["d3_close"],
        "X5_D5_close": ev["d5_close"],
    }


# ── Step 4: Stop Overlay ────────────────────────────────────────────────────

def apply_stop(entry_price, entry_bar_idx, initial_stop, exit_label,
               exit_price, d0_m5_bars, d1_daily, d2_daily, d3_daily, d5_daily):
    """
    Layer B: check if stop is hit before exit.
    Returns (final_exit_price, exit_reason).
    """
    if initial_stop is None or entry_price is None:
        return exit_price, "no_stop"

    # For intraday exit (X0), check M5 bars from entry to end of D0
    if exit_label == "X0_D0_close":
        for bar in d0_m5_bars[entry_bar_idx:]:
            if bar["open"] < initial_stop:
                return bar["open"], "stop_gap"
            if bar["low"] <= initial_stop:
                return initial_stop, "stop_hit"
        return exit_price, "held"

    # For overnight+ exits, first check remaining D0 bars
    for bar in d0_m5_bars[entry_bar_idx:]:
        if bar["open"] < initial_stop:
            return bar["open"], "stop_gap"
        if bar["low"] <= initial_stop:
            return initial_stop, "stop_hit"

    # Then check daily bars D1..Dn
    daily_sequence = []
    if exit_label in ("X1_D1_open",):
        # Only need D1 open
        if d1_daily and d1_daily["open"] < initial_stop:
            return d1_daily["open"], "stop_gap_d1"
        return exit_price, "held"

    if exit_label in ("X2_D1_close",):
        daily_sequence = [("D1", d1_daily)]
    elif exit_label == "X3_D2_close":
        daily_sequence = [("D1", d1_daily), ("D2", d2_daily)]
    elif exit_label == "X4_D3_close":
        daily_sequence = [("D1", d1_daily), ("D2", d2_daily), ("D3", d3_daily)]
    elif exit_label == "X5_D5_close":
        daily_sequence = [("D1", d1_daily), ("D2", d2_daily), ("D3", d3_daily), ("D5", d5_daily)]

    for day_label, dd in daily_sequence:
        if dd is None:
            continue
        if dd["open"] < initial_stop:
            return dd["open"], f"stop_gap_{day_label}"
        if dd["low"] <= initial_stop:
            return initial_stop, f"stop_hit_{day_label}"

    return exit_price, "held"


# ── Step 5: Horse Race ──────────────────────────────────────────────────────

def compute_return(entry, exit_p):
    if entry is None or exit_p is None or entry == 0:
        return None
    return (exit_p - entry) / entry


def stats_for_returns(rets):
    """Compute stats for a list of returns."""
    rets = [r for r in rets if r is not None]
    if not rets:
        return {}
    n = len(rets)
    mean = sum(rets) / n
    median = sorted(rets)[n // 2]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    wr = len(wins) / n if n > 0 else 0
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else (999.0 if wins else 0)
    pct25 = sorted(rets)[max(0, int(n * 0.25))]
    pct5 = sorted(rets)[max(0, int(n * 0.05))]
    best = max(rets)
    worst = min(rets)
    return {
        "N": n, "mean_gross": round(mean, 6),
        "mean_net_3bps": round(mean - 0.0006, 6),
        "mean_net_5bps": round(mean - 0.0010, 6),
        "median": round(median, 6), "wr": round(wr, 4),
        "pf": round(min(pf, 999.0), 2),
        "pct25": round(pct25, 6), "pct5": round(pct5, 6),
        "best": round(best, 6), "worst": round(worst, 6),
    }


def run_horse_race(cap_label):
    print(f"\n{'='*70}")
    print(f"HORSE RACE — gap cap {cap_label}")
    print(f"{'='*70}")

    events = load_trigger_csv(cap_label)
    print(f"Loaded {len(events)} events")

    # Pre-load M5 and daily data per ticker
    tickers = set(e["ticker"] for e in events)
    m5_data = {}
    daily_data = {}
    for t in tickers:
        m5_data[t] = load_m5(t)
        daily_data[t] = load_daily(t)

    def get_m5_date(ticker, date_str):
        return [b for b in m5_data[ticker] if b["date"] == date_str]

    def get_daily(ticker, date_str):
        return daily_data[ticker].get(date_str)

    # Build trades for every Entry × Exit × Stop combination
    entry_labels = ["E1", "E2", "E3", "C1", "C2", "C3"]
    exit_labels = ["X0_D0_close", "X1_D1_open", "X2_D1_close",
                   "X3_D2_close", "X4_D3_close", "X5_D5_close"]
    stop_layers = ["A_no_stop", "B_with_stop"]

    # Collect all trades
    all_trades = []  # list of dicts
    race_results = {}  # (entry, exit, stop) -> list of returns

    for ev in events:
        ticker = ev["ticker"]
        d0 = ev["d0_date"]
        d0_m5 = get_m5_date(ticker, d0)
        if not d0_m5:
            continue

        # Get forward daily data for stop overlay
        d1_daily = get_daily(ticker, ev.get("d1_date") or "")  # might be str
        d2_daily = get_daily(ticker, ev.get("d2_date") or "")
        d3_daily = get_daily(ticker, ev.get("d3_date") or "")
        d5_daily = get_daily(ticker, ev.get("d5_date") or "")

        # Fix: d1_date etc might not be in ev dict from CSV — derive from daily
        # Actually they're not in the trigger CSV. Derive from daily data.
        trading_days = sorted(daily_data[ticker].keys())
        if d0 in trading_days:
            d0_idx = trading_days.index(d0)
            d1_date = trading_days[d0_idx + 1] if d0_idx + 1 < len(trading_days) else None
            d2_date = trading_days[d0_idx + 2] if d0_idx + 2 < len(trading_days) else None
            d3_date = trading_days[d0_idx + 3] if d0_idx + 3 < len(trading_days) else None
            d5_date = trading_days[d0_idx + 5] if d0_idx + 5 < len(trading_days) else None
        else:
            continue

        d1_daily = daily_data[ticker].get(d1_date) if d1_date else None
        d2_daily = daily_data[ticker].get(d2_date) if d2_date else None
        d3_daily = daily_data[ticker].get(d3_date) if d3_date else None
        d5_daily = daily_data[ticker].get(d5_date) if d5_date else None

        # Compute entries
        entries = compute_entries(ev, d0_m5)
        exits = compute_exits(ev)

        # Determine entry bar index for stop overlay
        # For E1: trigger_bar_idx + 1
        # For E2: trigger_bar_idx + 2
        # For E3/C2/C3: find 12:00 bar index
        # For C1: find 10:00 bar index
        tbi = ev.get("trigger_bar_idx", "")
        tbi = int(float(tbi)) if tbi not in ("", None) else None

        entry_bar_indices = {}
        if tbi is not None and tbi + 1 < len(d0_m5):
            entry_bar_indices["E1"] = tbi + 1
        if tbi is not None and tbi + 2 < len(d0_m5):
            entry_bar_indices["E2"] = tbi + 2

        # Find bar indices for time-based entries
        for i, bar in enumerate(d0_m5):
            if bar["time"] == "10:00":
                entry_bar_indices["C1"] = i
            if bar["time"] == "12:00":
                entry_bar_indices["C2"] = i
                entry_bar_indices["C3"] = i
                entry_bar_indices["E3"] = i

        for entry_label in entry_labels:
            entry_price = entries.get(entry_label)
            if entry_price is None:
                continue

            ebi = entry_bar_indices.get(entry_label)

            for exit_label in exit_labels:
                exit_price = exits.get(exit_label)
                if exit_price is None:
                    continue

                for stop_layer in stop_layers:
                    if stop_layer == "A_no_stop":
                        final_exit = exit_price
                        exit_reason = "held"
                        stop_count = 0
                    else:
                        # Layer B — with stop
                        if ebi is not None and ev["initial_stop"] is not None:
                            final_exit, exit_reason = apply_stop(
                                entry_price, ebi, ev["initial_stop"],
                                exit_label, exit_price,
                                d0_m5, d1_daily, d2_daily, d3_daily, d5_daily
                            )
                        else:
                            final_exit = exit_price
                            exit_reason = "no_stop_data"

                    ret = compute_return(entry_price, final_exit)
                    if ret is None:
                        continue

                    key = (entry_label, exit_label, stop_layer)
                    race_results.setdefault(key, []).append(ret)

                    all_trades.append({
                        "event_id": ev["event_id"],
                        "ticker": ticker,
                        "d0_date": d0,
                        "gap_pct": ev["gap_pct"],
                        "entry": entry_label,
                        "exit": exit_label,
                        "stop": stop_layer,
                        "entry_price": round(entry_price, 4),
                        "exit_price": round(final_exit, 4),
                        "return_gross": round(ret, 6),
                        "exit_reason": exit_reason,
                        "eps_surprise_pct": ev.get("eps_surprise_pct", ""),
                        "revenue_surprise_pct": ev.get("revenue_surprise_pct", ""),
                        "release_timing": ev["release_timing"],
                    })

    # Build horse race table
    horse_race = []
    for (entry_label, exit_label, stop_layer), rets in sorted(race_results.items()):
        s = stats_for_returns(rets)
        if not s:
            continue
        row = {"entry": entry_label, "exit": exit_label, "stop": stop_layer}
        row.update(s)
        # Count stops hit
        if stop_layer == "B_with_stop":
            stops_hit = sum(1 for t in all_trades
                           if t["entry"] == entry_label
                           and t["exit"] == exit_label
                           and t["stop"] == stop_layer
                           and "stop" in t["exit_reason"])
            row["stops_hit"] = stops_hit
        else:
            row["stops_hit"] = 0
        horse_race.append(row)

    # Write horse race CSV
    hr_path = os.path.join(OUT, f"module8_horse_race_{cap_label}.csv")
    if horse_race:
        cols = list(horse_race[0].keys())
        with open(hr_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(horse_race)
        print(f"Wrote {len(horse_race)} combos to {hr_path}")

    # Write all trades CSV for robustness script
    trades_path = os.path.join(OUT, f"module8_all_trades_{cap_label}.csv")
    if all_trades:
        cols = list(all_trades[0].keys())
        with open(trades_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(all_trades)
        print(f"Wrote {len(all_trades)} trades to {trades_path}")

    # Print horse race table (Layer A only, sorted by mean_gross desc)
    print(f"\n{'─'*90}")
    print(f"HORSE RACE TABLE — Layer A (no stop) — {cap_label}")
    print(f"{'─'*90}")
    print(f"{'Entry':5s} {'Exit':12s} {'N':>3s} {'Mean%':>7s} {'Med%':>7s} {'WR':>5s} "
          f"{'PF':>6s} {'Net3bp%':>8s} {'Net5bp%':>8s} {'Best%':>7s} {'Worst%':>7s}")
    print(f"{'─'*90}")
    layer_a = sorted([r for r in horse_race if r["stop"] == "A_no_stop"],
                     key=lambda x: x["mean_gross"], reverse=True)
    for r in layer_a:
        flag = " ◀" if r["N"] < 10 else ""
        print(f"{r['entry']:5s} {r['exit']:12s} {r['N']:3d} "
              f"{r['mean_gross']*100:7.2f} {r['median']*100:7.2f} {r['wr']*100:5.1f} "
              f"{r['pf']:6.2f} {r['mean_net_3bps']*100:8.2f} {r['mean_net_5bps']*100:8.2f} "
              f"{r['best']*100:7.2f} {r['worst']*100:7.2f}{flag}")

    # Print Layer B
    print(f"\n{'─'*90}")
    print(f"HORSE RACE TABLE — Layer B (with stop) — {cap_label}")
    print(f"{'─'*90}")
    print(f"{'Entry':5s} {'Exit':12s} {'N':>3s} {'Mean%':>7s} {'Med%':>7s} {'WR':>5s} "
          f"{'PF':>6s} {'Net3bp%':>8s} {'Stops':>5s} {'Best%':>7s} {'Worst%':>7s}")
    print(f"{'─'*90}")
    layer_b = sorted([r for r in horse_race if r["stop"] == "B_with_stop"],
                     key=lambda x: x["mean_gross"], reverse=True)
    for r in layer_b:
        flag = " ◀" if r["N"] < 10 else ""
        print(f"{r['entry']:5s} {r['exit']:12s} {r['N']:3d} "
              f"{r['mean_gross']*100:7.2f} {r['median']*100:7.2f} {r['wr']*100:5.1f} "
              f"{r['pf']:6.2f} {r['mean_net_3bps']*100:8.2f} {r['stops_hit']:5d} "
              f"{r['best']*100:7.2f} {r['worst']*100:7.2f}{flag}")

    # Key comparison: trigger vs control
    print(f"\n{'─'*70}")
    print("KEY COMPARISON: Trigger (E1) vs Control (C1, C2) — Layer A, all exits")
    print(f"{'─'*70}")
    for exit_label in exit_labels:
        e1 = next((r for r in horse_race
                    if r["entry"] == "E1" and r["exit"] == exit_label
                    and r["stop"] == "A_no_stop"), None)
        c1 = next((r for r in horse_race
                    if r["entry"] == "C1" and r["exit"] == exit_label
                    and r["stop"] == "A_no_stop"), None)
        c2 = next((r for r in horse_race
                    if r["entry"] == "C2" and r["exit"] == exit_label
                    and r["stop"] == "A_no_stop"), None)
        if e1 and c1 and c2:
            e1_beats_c1 = "YES" if e1["mean_gross"] > c1["mean_gross"] else "NO"
            e1_beats_c2 = "YES" if e1["mean_gross"] > c2["mean_gross"] else "NO"
            print(f"  {exit_label:12s}  E1={e1['mean_gross']*100:+.2f}%  "
                  f"C1={c1['mean_gross']*100:+.2f}%  C2={c2['mean_gross']*100:+.2f}%  "
                  f"E1>C1={e1_beats_c1}  E1>C2={e1_beats_c2}")

    return horse_race, all_trades


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("MODULE 8 CLEAN RE-TEST — HORSE RACE (Steps 2-5)")
    print("ANT-6 Pass A: Method Cleanup")
    print("=" * 70)

    for cap in ["cap10", "cap15"]:
        run_horse_race(cap)

    print("\n✓ Horse race complete. Run module8_robustness.py next.")


if __name__ == "__main__":
    main()
