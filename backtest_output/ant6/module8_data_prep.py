#!/usr/bin/env python3
"""
Module 8 Clean Re-Test — Data Prep (Steps 0-1)
ANT-6 Pass A: Method Cleanup
Builds event master, computes path-valid triggers.
"""

import csv
import os
import json
from datetime import datetime, timedelta, date
from collections import defaultdict, Counter
from zoneinfo import ZoneInfo

# ── Constants ────────────────────────────────────────────────────────────────

BASE = "/home/user/stock-data-mining/backtest_output"
OUT = os.path.join(BASE, "ant6")
os.makedirs(OUT, exist_ok=True)

TICKERS_27 = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",
    "TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM",
    "MU", "INTC", "COST",
    "COIN", "MSTR", "MARA",
    "C", "GS", "V", "BA", "JPM",
    "BABA", "JD", "BIDU",
]

EXCLUDED_TICKERS = {"SMCI", "ARM", "INTC", "MSTR", "JD"}
TICKERS = [t for t in TICKERS_27 if t not in EXCLUDED_TICKERS]

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

PRIMARY = {
    "gap_floor": 0.05,
    "gap_caps": [0.10, 0.15],
    "recovery_threshold": 0.35,
    "trigger_window_start": "10:00",
    "trigger_window_end": "13:00",
}


# ── Data Loading ─────────────────────────────────────────────────────────────

def load_earnings_calendar():
    """Load earnings calendar from cached CSV."""
    path = os.path.join(BASE, "ant1", "earnings_calendar_full.csv")
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return rows


def load_daily(ticker):
    """Load daily OHLCV for a ticker. Returns dict keyed by date string."""
    path = os.path.join(BASE, f"{ticker}_daily.csv")
    if not os.path.exists(path):
        return {}
    daily = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            d = row["date"]
            daily[d] = {
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(float(row["Volume"])),
            }
    return daily


def load_m5(ticker):
    """Load M5 bars for a ticker. Timestamps assumed ET (from cached CSVs).
    Returns list of dicts sorted by datetime."""
    path = os.path.join(BASE, f"{ticker}_m5_regsess.csv")
    if not os.path.exists(path):
        return []
    bars = []
    with open(path) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            bars.append({
                "dt": dt,
                "date": dt.strftime("%Y-%m-%d"),
                "time": dt.strftime("%H:%M"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(float(row["Volume"])),
            })
    bars.sort(key=lambda x: x["dt"])
    return bars


def get_m5_for_date(m5_bars, date_str):
    """Get all M5 bars for a specific date."""
    return [b for b in m5_bars if b["date"] == date_str]


def get_trading_days(daily):
    """Get sorted list of trading day strings."""
    return sorted(daily.keys())


def next_trading_day(trading_days, d, offset=1):
    """Get the trading day offset days after d."""
    if d not in trading_days:
        # Find nearest following trading day
        for td in trading_days:
            if td > d:
                d = td
                break
        else:
            return None
        offset -= 1
    idx = trading_days.index(d)
    target = idx + offset
    if 0 <= target < len(trading_days):
        return trading_days[target]
    return None


def prev_trading_day(trading_days, d, offset=1):
    """Get the trading day offset days before d."""
    if d not in trading_days:
        # Find nearest preceding trading day
        for td in reversed(trading_days):
            if td < d:
                d = td
                break
        else:
            return None
        offset -= 1
    idx = trading_days.index(d)
    target = idx - offset
    if 0 <= target < len(trading_days):
        return trading_days[target]
    return None


# ── Step 0: Event Master ────────────────────────────────────────────────────

def compute_d0(earnings_date_str, time_of_day, trading_days):
    """
    AMC on date d → D0 = next trading day.
    BMO on date d → D0 = same trading day (if it's a trading day, else next).
    """
    if time_of_day == "AMC":
        return next_trading_day(trading_days, earnings_date_str, offset=1)
    elif time_of_day == "BMO":
        if earnings_date_str in trading_days:
            return earnings_date_str
        # If earnings_date is not a trading day, find next
        for td in trading_days:
            if td >= earnings_date_str:
                return td
        return None
    return None  # UNKNOWN


def build_event_master():
    """Build the complete event master table."""
    ec = load_earnings_calendar()

    # Pre-load all data
    print("Loading daily and M5 data for all tickers...")
    all_daily = {}
    all_m5 = {}
    all_trading_days = {}
    for t in TICKERS:
        all_daily[t] = load_daily(t)
        all_m5[t] = load_m5(t)
        all_trading_days[t] = get_trading_days(all_daily[t])
        print(f"  {t}: {len(all_daily[t])} daily bars, {len(all_m5[t])} M5 bars")

    events = []
    exclusion_log = []
    event_id = 0

    for row in ec:
        ticker = row["ticker"]
        earnings_date = row["earnings_date"]
        tod = row["time_of_day"]

        # Skip excluded tickers
        if ticker in EXCLUDED_TICKERS:
            continue

        # Skip if ticker not in our universe
        if ticker not in TICKERS:
            continue

        event_id += 1
        ev = {
            "event_id": event_id,
            "ticker": ticker,
            "earnings_date": earnings_date,
            "release_timing": tod,
            "eps_estimated": row.get("eps_estimated", ""),
            "eps_actual": row.get("eps_actual", ""),
            "surprise_pct": row.get("surprise_pct", ""),
            "revenue_estimated": row.get("revenue_estimated", ""),
            "revenue_actual": row.get("revenue_actual", ""),
            "revenue_surprise_pct": row.get("revenue_surprise_pct", ""),
            "source": row.get("source", ""),
        }

        daily = all_daily[ticker]
        trading_days = all_trading_days[ticker]

        # Check timing
        if tod not in ("BMO", "AMC"):
            ev.update({"excluded": True, "exclusion_reason": "unknown_timing",
                        "d0_date": "", "prev_close": "", "d0_open": "",
                        "gap_abs": "", "gap_pct": "",
                        "has_m5": False, "has_daily_d5": False})
            events.append(ev)
            exclusion_log.append(f"Event {event_id} {ticker} {earnings_date}: UNKNOWN timing")
            continue

        # Compute D0
        d0 = compute_d0(earnings_date, tod, trading_days)
        if not d0:
            ev.update({"excluded": True, "exclusion_reason": "no_d0_trading_day",
                        "d0_date": "", "prev_close": "", "d0_open": "",
                        "gap_abs": "", "gap_pct": "",
                        "has_m5": False, "has_daily_d5": False})
            events.append(ev)
            exclusion_log.append(f"Event {event_id} {ticker} {earnings_date}: no D0 trading day")
            continue

        ev["d0_date"] = d0

        # D-1
        d_minus1 = prev_trading_day(trading_days, d0, 1)
        if not d_minus1 or d_minus1 not in daily:
            ev.update({"excluded": True, "exclusion_reason": "missing_d_minus1",
                        "prev_close": "", "d0_open": "",
                        "gap_abs": "", "gap_pct": "",
                        "has_m5": False, "has_daily_d5": False})
            events.append(ev)
            exclusion_log.append(f"Event {event_id} {ticker} {earnings_date}: missing D-1 daily")
            continue

        prev_close = daily[d_minus1]["close"]
        ev["prev_close"] = prev_close

        # D0 open
        if d0 not in daily:
            ev.update({"excluded": True, "exclusion_reason": "missing_d0_daily",
                        "d0_open": "", "gap_abs": "", "gap_pct": "",
                        "has_m5": False, "has_daily_d5": False})
            events.append(ev)
            exclusion_log.append(f"Event {event_id} {ticker} {earnings_date}: missing D0 daily")
            continue

        d0_open = daily[d0]["open"]
        ev["d0_open"] = d0_open

        # Gap computation (positive = gap down)
        gap_abs = prev_close - d0_open
        gap_pct = gap_abs / prev_close if prev_close != 0 else 0
        ev["gap_abs"] = round(gap_abs, 4)
        ev["gap_pct"] = round(gap_pct, 6)

        # Check M5 coverage on D0
        d0_m5 = get_m5_for_date(all_m5[ticker], d0)
        has_m5 = len(d0_m5) >= 70  # expect ~78 bars, allow some slack
        ev["has_m5"] = has_m5

        # Check D-1..D5 daily coverage
        d1 = next_trading_day(trading_days, d0, 1)
        d2 = next_trading_day(trading_days, d0, 2)
        d3 = next_trading_day(trading_days, d0, 3)
        d5 = next_trading_day(trading_days, d0, 5)

        has_daily_d5 = all(
            d is not None and d in daily
            for d in [d_minus1, d0, d1, d2, d3, d5]
        )
        ev["has_daily_d5"] = has_daily_d5

        # Store forward dates for later use
        ev["d_minus1"] = d_minus1
        ev["d1_date"] = d1 or ""
        ev["d2_date"] = d2 or ""
        ev["d3_date"] = d3 or ""
        ev["d5_date"] = d5 or ""

        # Determine exclusion
        excluded = False
        reason = ""
        if not has_m5:
            excluded = True
            reason = "missing_d0_m5"
        elif not has_daily_d5:
            excluded = True
            reason = "missing_daily_d5"

        ev["excluded"] = excluded
        ev["exclusion_reason"] = reason

        if excluded:
            exclusion_log.append(
                f"Event {event_id} {ticker} {earnings_date} D0={d0}: {reason} "
                f"(m5_bars={len(d0_m5)}, daily_d5={has_daily_d5})"
            )

        events.append(ev)

    return events, exclusion_log, all_daily, all_m5, all_trading_days


def write_event_master(events):
    """Write event master CSV."""
    cols = [
        "event_id", "ticker", "earnings_date", "release_timing", "d0_date",
        "prev_close", "d0_open", "gap_abs", "gap_pct",
        "eps_actual", "eps_estimated", "surprise_pct",
        "revenue_actual", "revenue_estimated", "revenue_surprise_pct",
        "has_m5", "has_daily_d5", "excluded", "exclusion_reason",
    ]
    path = os.path.join(OUT, "module8_event_master.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for ev in events:
            w.writerow(ev)
    print(f"Wrote {len(events)} events to {path}")


def write_universe_audit(events):
    """Write universe audit CSV and summary."""
    total = len(events)
    known_timing = sum(1 for e in events if e["release_timing"] in ("BMO", "AMC"))
    not_excluded = [e for e in events if not e["excluded"]]

    # Gap-down >= 5% among non-excluded
    gap_5pct = sum(
        1 for e in not_excluded
        if isinstance(e.get("gap_pct"), (int, float)) and e["gap_pct"] >= 0.05
    )
    has_m5 = sum(1 for e in events if e.get("has_m5"))
    has_daily = sum(1 for e in events if e.get("has_daily_d5"))
    eligible = len(not_excluded)

    # Per ticker
    ticker_counts = Counter(e["ticker"] for e in not_excluded)
    # Per year
    year_counts = Counter()
    for e in not_excluded:
        d0 = e.get("d0_date", "")
        if d0:
            year_counts[d0[:4]] += 1

    # Gap-down eligible (non-excluded AND gap >= 5%)
    gap_eligible = [
        e for e in not_excluded
        if isinstance(e.get("gap_pct"), (int, float)) and e["gap_pct"] >= 0.05
    ]

    audit = {
        "total_events_in_calendar": total,
        "canonical_tickers_27": 27,
        "tickers_with_data": len(TICKERS),
        "excluded_tickers": sorted(EXCLUDED_TICKERS),
        "excluded_ticker_reason": "no cached daily/M5 data available",
        "events_known_bmo_amc": known_timing,
        "events_with_gap_gte_5pct": gap_5pct,
        "events_with_full_m5": has_m5,
        "events_with_full_daily_d5": has_daily,
        "eligible_events_total": eligible,
        "gap_down_eligible_events": len(gap_eligible),
        "per_ticker": dict(sorted(ticker_counts.items())),
        "per_year": dict(sorted(year_counts.items())),
    }

    path = os.path.join(OUT, "module8_universe_audit.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        for k, v in audit.items():
            w.writerow([k, json.dumps(v) if isinstance(v, (dict, list)) else v])

    # Also write JSON for easy consumption
    path_json = os.path.join(OUT, "module8_universe_audit.json")
    with open(path_json, "w") as f:
        json.dump(audit, f, indent=2)

    print("\n" + "=" * 70)
    print("UNIVERSE AUDIT")
    print("=" * 70)
    for k, v in audit.items():
        print(f"  {k}: {v}")
    print("=" * 70)

    return audit, gap_eligible


# ── Step 1: Path-Valid Trigger Computation ──────────────────────────────────

def compute_triggers(gap_eligible_events, all_daily, all_m5, all_trading_days,
                     gap_floor, gap_cap, recovery_threshold):
    """
    For each eligible gap-down event, compute path-valid trigger.
    Returns list of trigger event dicts.
    """
    trigger_events = []

    for ev in gap_eligible_events:
        ticker = ev["ticker"]
        d0 = ev["d0_date"]
        gap_pct = ev["gap_pct"]
        gap_abs = ev["gap_abs"]
        prev_close = ev["prev_close"]
        d0_open = ev["d0_open"]

        # Apply gap filters
        if gap_pct < gap_floor:
            continue
        if gap_pct >= gap_cap:
            continue

        daily = all_daily[ticker]
        trading_days = all_trading_days[ticker]
        d0_m5 = get_m5_for_date(all_m5[ticker], d0)

        if not d0_m5:
            continue

        # Sort chronologically
        d0_m5.sort(key=lambda x: x["dt"])

        # D0 close = last bar close
        d0_close = d0_m5[-1]["close"]

        # Forward dates and prices
        d1 = ev.get("d1_date", "")
        d2 = ev.get("d2_date", "")
        d3 = ev.get("d3_date", "")
        d5 = ev.get("d5_date", "")

        d1_open = daily[d1]["open"] if d1 and d1 in daily else None
        d1_close = daily[d1]["close"] if d1 and d1 in daily else None
        d2_close = daily[d2]["close"] if d2 and d2 in daily else None
        d3_close = daily[d3]["close"] if d3 and d3 in daily else None
        d5_close = daily[d5]["close"] if d5 and d5 in daily else None

        # Path-valid trigger computation
        running_low = float("inf")
        running_low_time = None
        trigger_fired = False
        trigger_bar = None
        trigger_time = None
        trigger_recovery = None
        trigger_running_low = None
        entry_price = None
        initial_stop = None

        for i, bar in enumerate(d0_m5):
            bar_time = bar["time"]  # HH:MM

            # Update running low
            if bar["low"] < running_low:
                running_low = bar["low"]
                running_low_time = bar_time

            # Check trigger (10:00-13:00 window)
            if not trigger_fired and "10:00" <= bar_time <= "13:00":
                # running_low must be from BEFORE this bar
                if running_low_time is not None and running_low_time < bar_time:
                    if gap_abs > 0:
                        recovery_ratio = (bar["close"] - running_low) / gap_abs
                    else:
                        recovery_ratio = 0

                    if recovery_ratio >= recovery_threshold:
                        trigger_fired = True
                        trigger_bar = bar
                        trigger_time = bar_time
                        trigger_recovery = round(recovery_ratio, 4)
                        trigger_running_low = running_low

                        # Entry = next bar's open
                        if i + 1 < len(d0_m5):
                            entry_price = d0_m5[i + 1]["open"]
                            initial_stop = running_low
                        else:
                            # Trigger on last bar — no entry possible
                            trigger_fired = False
                        break

        # Compute overshoot (how far below open the running low went)
        # Use the final running_low at trigger time or end of day
        if trigger_fired:
            overshoot = (d0_open - trigger_running_low) / gap_abs if gap_abs > 0 else 0
        else:
            # Compute overall day low
            day_low = min(b["low"] for b in d0_m5)
            overshoot = (d0_open - day_low) / gap_abs if gap_abs > 0 else 0

        # Also find specific intraday bar prices for control entries
        bar_10_00 = next((b for b in d0_m5 if b["time"] == "10:00"), None)
        bar_12_00 = next((b for b in d0_m5 if b["time"] == "12:00"), None)

        tev = {
            "event_id": ev["event_id"],
            "ticker": ticker,
            "d0_date": d0,
            "earnings_date": ev["earnings_date"],
            "release_timing": ev["release_timing"],
            "gap_pct": round(gap_pct, 6),
            "gap_abs": round(gap_abs, 4),
            "prev_close": prev_close,
            "d0_open": d0_open,
            "trigger_fired": trigger_fired,
            "trigger_time_et": trigger_time or "",
            "trigger_recovery_ratio": trigger_recovery or "",
            "trigger_running_low": round(trigger_running_low, 4) if trigger_running_low else "",
            "overshoot_ratio": round(overshoot, 4),
            "entry_price": round(entry_price, 4) if entry_price else "",
            "initial_stop": round(initial_stop, 4) if initial_stop else "",
            "d0_close": round(d0_close, 4),
            "d1_open": round(d1_open, 4) if d1_open else "",
            "d1_close": round(d1_close, 4) if d1_close else "",
            "d2_close": round(d2_close, 4) if d2_close else "",
            "d3_close": round(d3_close, 4) if d3_close else "",
            "d5_close": round(d5_close, 4) if d5_close else "",
            "eps_surprise_pct": ev.get("surprise_pct", ""),
            "revenue_surprise_pct": ev.get("revenue_surprise_pct", ""),
            # Control entry prices
            "bar_10_00_open": round(bar_10_00["open"], 4) if bar_10_00 else "",
            "bar_12_00_open": round(bar_12_00["open"], 4) if bar_12_00 else "",
            # Store trigger bar index for stop overlay
            "trigger_bar_idx": d0_m5.index(trigger_bar) if trigger_fired and trigger_bar else "",
            "d0_m5_count": len(d0_m5),
            "gap_cap_used": gap_cap,
        }

        trigger_events.append(tev)

    return trigger_events


def write_trigger_events(trigger_events, suffix=""):
    """Write trigger events CSV."""
    if not trigger_events:
        print(f"WARNING: No trigger events to write{suffix}")
        return

    cols = list(trigger_events[0].keys())
    path = os.path.join(OUT, f"module8_trigger_events{suffix}.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(trigger_events)
    print(f"Wrote {len(trigger_events)} trigger events to {path}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("MODULE 8 CLEAN RE-TEST — DATA PREP (Steps 0-1)")
    print("ANT-6 Pass A: Method Cleanup")
    print("=" * 70)

    # Step 0: Build event master
    print("\n▶ STEP 0: Building event master...")
    events, exclusion_log, all_daily, all_m5, all_trading_days = build_event_master()
    write_event_master(events)

    # Write exclusion log
    with open(os.path.join(OUT, "module8_exclusion_log.txt"), "w") as f:
        f.write(f"Exclusion Log — {len(exclusion_log)} excluded events\n")
        f.write(f"Excluded tickers (no data): {sorted(EXCLUDED_TICKERS)}\n\n")
        for line in exclusion_log:
            f.write(line + "\n")
    print(f"Wrote exclusion log: {len(exclusion_log)} entries")

    # Universe audit
    audit, gap_eligible = write_universe_audit(events)

    # Coverage check
    n_gap = len(gap_eligible)
    print(f"\n{'*' * 50}")
    print(f"Gap-down eligible events (gap >= 5%, not excluded): {n_gap}")
    if n_gap < 15:
        print("⚠ WARNING: N < 15 — test is UNDERPOWERED")
    print(f"{'*' * 50}")

    # Step 1: Compute triggers for both gap caps
    for gap_cap in PRIMARY["gap_caps"]:
        suffix = f"_cap{int(gap_cap*100)}"
        print(f"\n▶ STEP 1: Computing triggers (gap_cap={gap_cap})...")
        trigger_events = compute_triggers(
            gap_eligible, all_daily, all_m5, all_trading_days,
            gap_floor=PRIMARY["gap_floor"],
            gap_cap=gap_cap,
            recovery_threshold=PRIMARY["recovery_threshold"],
        )
        write_trigger_events(trigger_events, suffix)

        # Summary
        n_total = len(trigger_events)
        n_triggered = sum(1 for t in trigger_events if t["trigger_fired"])
        print(f"  Gap range: {PRIMARY['gap_floor']*100:.0f}%-{gap_cap*100:.0f}%")
        print(f"  Total eligible events: {n_total}")
        print(f"  Trigger fired: {n_triggered}")
        print(f"  Trigger rate: {n_triggered/n_total*100:.1f}%" if n_total > 0 else "  N/A")

        if n_triggered > 0:
            times = [t["trigger_time_et"] for t in trigger_events if t["trigger_fired"]]
            print(f"  Trigger times: {Counter(times).most_common(5)}")

    # Save metadata for horse_race script
    meta = {
        "gap_floor": PRIMARY["gap_floor"],
        "gap_caps": PRIMARY["gap_caps"],
        "recovery_threshold": PRIMARY["recovery_threshold"],
        "tickers": TICKERS,
        "excluded_tickers": sorted(EXCLUDED_TICKERS),
        "n_eligible": n_gap,
    }
    with open(os.path.join(OUT, "module8_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print("\n✓ Data prep complete. Run module8_horse_race.py next.")


if __name__ == "__main__":
    main()
