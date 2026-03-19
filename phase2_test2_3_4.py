"""Phase 2: Tests 2, 3, 4 — RS Persistence, Forward Returns, Laggard Rebound"""
import pandas as pd
import numpy as np
from scipy import stats
import json, os

OUT_DIR = "backtest_output"
TRADE_UNIVERSE = [
    "AAPL","AMD","AMZN","AVGO","BA","BABA","BIDU","C","COIN","COST",
    "GOOGL","GS","IBIT","JPM","MARA","META","MSFT","MU","NVDA",
    "PLTR","SNOW","TSLA","TSM","TXN","V"
]

# Load stress days
with open(os.path.join(OUT_DIR, "stress_days.json")) as f:
    stress_dates = [pd.Timestamp(d) for d in json.load(f)]

# Load M5 regular session data
m5 = {}
for tk in TRADE_UNIVERSE + ["SPY"]:
    m5[tk] = pd.read_csv(os.path.join(OUT_DIR, f"{tk}_m5_regsess.csv"), parse_dates=["Datetime"])

def get_price_at_time(df, date, target_time):
    """Get close price at or just before target_time on given date."""
    day = df[df["Datetime"].dt.date == date.date()]
    if day.empty:
        return np.nan
    mask = day["Datetime"].dt.time <= target_time
    if mask.any():
        return day[mask].iloc[-1]["Close"]
    return np.nan

def get_price_first_bar(df, date):
    """Get first bar close price (= open reference per spec)."""
    day = df[df["Datetime"].dt.date == date.date()]
    return day.iloc[0]["Close"] if not day.empty else np.nan

def get_price_last_bar(df, date):
    """Get last bar close price (= EOD)."""
    day = df[df["Datetime"].dt.date == date.date()]
    return day.iloc[-1]["Close"] if not day.empty else np.nan

from datetime import time as dtime
T_0930 = dtime(9, 30)
T_1200 = dtime(12, 0)
T_1230 = dtime(12, 30)
T_1300 = dtime(13, 0)
T_1400 = dtime(14, 0)
T_1555 = dtime(15, 55)

# ── Test 2: Cross-Sectional RS Persistence ──────────────────────────────
print("=" * 60)
print("TEST 2: CROSS-SECTIONAL RS PERSISTENCE (AM → PM)")
print("=" * 60)

spreads = []
quintile_results = {q: {"am": [], "pm": []} for q in range(1, 6)}

for sd in stress_dates:
    am_rets = {}
    pm_rets = {}
    for tk in TRADE_UNIVERSE:
        p_open = get_price_first_bar(m5[tk], sd)
        p_1230 = get_price_at_time(m5[tk], sd, T_1230)
        p_eod = get_price_last_bar(m5[tk], sd)
        if np.isnan(p_open) or np.isnan(p_1230) or np.isnan(p_eod) or p_open == 0 or p_1230 == 0:
            continue
        am_rets[tk] = (p_1230 / p_open) - 1
        pm_rets[tk] = (p_eod / p_1230) - 1

    if len(am_rets) < 20:
        continue

    # Rank by AM return (1=best)
    ranked = sorted(am_rets.keys(), key=lambda t: am_rets[t], reverse=True)
    n = len(ranked)
    q_size = n // 5

    for q in range(5):
        start = q * q_size
        end = start + q_size if q < 4 else n
        q_tickers = ranked[start:end]
        avg_am = np.mean([am_rets[t] for t in q_tickers])
        avg_pm = np.mean([pm_rets[t] for t in q_tickers])
        quintile_results[q + 1]["am"].append(avg_am)
        quintile_results[q + 1]["pm"].append(avg_pm)

    q1_pm = np.mean([pm_rets[t] for t in ranked[:q_size]])
    q5_pm = np.mean([pm_rets[t] for t in ranked[-q_size:]])
    spreads.append(q1_pm - q5_pm)

print(f"\nN stress days analyzed: {len(spreads)}")
print(f"\n{'Quintile':<10} {'Avg AM Ret':>12} {'Avg PM Ret':>12} {'PM Hit Rate':>12} {'N':>5}")
print("-" * 55)
for q in range(1, 6):
    am_vals = quintile_results[q]["am"]
    pm_vals = quintile_results[q]["pm"]
    avg_am = np.mean(am_vals) * 100
    avg_pm = np.mean(pm_vals) * 100
    hit = np.mean([1 if v > 0 else 0 for v in pm_vals]) * 100
    print(f"Q{q} {'(best)' if q==1 else '(worst)' if q==5 else '':<8} {avg_am:>11.3f}% {avg_pm:>11.3f}% {hit:>10.1f}% {len(pm_vals):>5}")

avg_spread = np.mean(spreads) * 100
t_stat, p_val = stats.ttest_1samp(spreads, 0)
print(f"\nQ1-Q5 spread: {avg_spread:.3f}% (t={t_stat:.3f}, p={p_val:.4f})")

# Save Test 2 results
test2 = {"n_days": len(spreads), "avg_spread_pct": avg_spread, "t_stat": t_stat, "p_val": p_val,
         "quintiles": {f"Q{q}": {"avg_am": np.mean(quintile_results[q]["am"])*100,
                                  "avg_pm": np.mean(quintile_results[q]["pm"])*100,
                                  "pm_hit_rate": np.mean([1 if v>0 else 0 for v in quintile_results[q]["pm"]])*100}
                       for q in range(1,6)}}

# ── Test 3: RS Leader Forward Returns (Multi-Horizon) ──────────────────
print("\n" + "=" * 60)
print("TEST 3: RS LEADER FORWARD RETURNS (MULTI-HORIZON)")
print("=" * 60)

horizons = {"1h": T_1300, "2h": T_1400, "EOD": T_1555}
q_horizon_results = {q: {h: [] for h in horizons} for q in range(1, 6)}

for sd in stress_dates:
    # Rank at 12:00 by return since open
    rets_at_noon = {}
    fwd_rets = {h: {} for h in horizons}

    for tk in TRADE_UNIVERSE:
        p_open = get_price_first_bar(m5[tk], sd)
        p_noon = get_price_at_time(m5[tk], sd, T_1200)
        if np.isnan(p_open) or np.isnan(p_noon) or p_open == 0 or p_noon == 0:
            continue
        rets_at_noon[tk] = (p_noon / p_open) - 1
        for h_name, h_time in horizons.items():
            p_h = get_price_at_time(m5[tk], sd, h_time)
            fwd_rets[h_name][tk] = (p_h / p_noon) - 1 if not np.isnan(p_h) and p_noon != 0 else np.nan

    if len(rets_at_noon) < 20:
        continue

    ranked = sorted(rets_at_noon.keys(), key=lambda t: rets_at_noon[t], reverse=True)
    n = len(ranked)
    q_size = n // 5

    for q in range(5):
        start = q * q_size
        end = start + q_size if q < 4 else n
        q_tickers = ranked[start:end]
        for h_name in horizons:
            vals = [fwd_rets[h_name][t] for t in q_tickers if not np.isnan(fwd_rets[h_name].get(t, np.nan))]
            if vals:
                q_horizon_results[q + 1][h_name].append(np.mean(vals))

print(f"\n{'Quintile':<10}", end="")
for h in horizons:
    print(f" {h+' Avg':>10} {h+' Hit':>8}", end="")
print()
print("-" * 70)
for q in range(1, 6):
    label = f"Q{q} {'(best)' if q==1 else '(worst)' if q==5 else ''}"
    print(f"{label:<10}", end="")
    for h in horizons:
        vals = q_horizon_results[q][h]
        avg = np.mean(vals) * 100 if vals else 0
        hit = np.mean([1 if v > 0 else 0 for v in vals]) * 100 if vals else 0
        print(f" {avg:>9.3f}% {hit:>6.1f}%", end="")
    print()

# Best entry point
print("\nQ1-Q5 spread by horizon:")
test3_spreads = {}
for h in horizons:
    q1_avg = np.mean(q_horizon_results[1][h]) * 100 if q_horizon_results[1][h] else 0
    q5_avg = np.mean(q_horizon_results[5][h]) * 100 if q_horizon_results[5][h] else 0
    spread = q1_avg - q5_avg
    test3_spreads[h] = spread
    print(f"  {h}: {spread:.3f}%")
best_entry = max(test3_spreads, key=test3_spreads.get)
print(f"  Best entry horizon: {best_entry}")

# ── Test 4: Laggard Rebound vs Leader Continuation ─────────────────────
print("\n" + "=" * 60)
print("TEST 4: LAGGARD REBOUND VS LEADER CONTINUATION")
print("=" * 60)

recovery_q1, recovery_q5 = [], []
continuation_q1, continuation_q5 = [], []

for sd in stress_dates:
    # SPY PM return
    spy_noon = get_price_at_time(m5["SPY"], sd, T_1200)
    spy_eod = get_price_last_bar(m5["SPY"], sd)
    if np.isnan(spy_noon) or np.isnan(spy_eod) or spy_noon == 0:
        continue
    spy_pm = (spy_eod / spy_noon) - 1

    # Rank tickers at noon
    rets_at_noon = {}
    pm_rets = {}
    for tk in TRADE_UNIVERSE:
        p_open = get_price_first_bar(m5[tk], sd)
        p_noon = get_price_at_time(m5[tk], sd, T_1200)
        p_eod = get_price_last_bar(m5[tk], sd)
        if np.isnan(p_open) or np.isnan(p_noon) or np.isnan(p_eod) or p_open == 0 or p_noon == 0:
            continue
        rets_at_noon[tk] = (p_noon / p_open) - 1
        pm_rets[tk] = (p_eod / p_noon) - 1

    if len(rets_at_noon) < 20:
        continue

    ranked = sorted(rets_at_noon.keys(), key=lambda t: rets_at_noon[t], reverse=True)
    q_size = len(ranked) // 5
    q1_tickers = ranked[:q_size]
    q5_tickers = ranked[-q_size:]
    q1_pm = np.mean([pm_rets[t] for t in q1_tickers])
    q5_pm = np.mean([pm_rets[t] for t in q5_tickers])

    if spy_pm > 0:  # Recovery day
        recovery_q1.append(q1_pm)
        recovery_q5.append(q5_pm)
    else:  # Continuation day
        continuation_q1.append(q1_pm)
        continuation_q5.append(q5_pm)

print(f"\n{'Day Type':<16} {'N Days':>7} {'Q1 PM Avg':>12} {'Q5 PM Avg':>12} {'Spread':>10} {'Q5 Rebound':>12}")
print("-" * 72)
for label, q1_list, q5_list in [("Recovery", recovery_q1, recovery_q5),
                                  ("Continuation", continuation_q1, continuation_q5)]:
    n = len(q1_list)
    q1a = np.mean(q1_list) * 100 if q1_list else 0
    q5a = np.mean(q5_list) * 100 if q5_list else 0
    spread = q1a - q5a
    rebound = "YES" if q5a > q1a else "NO"
    print(f"{label:<16} {n:>7} {q1a:>11.3f}% {q5a:>11.3f}% {spread:>9.3f}% {rebound:>12}")

# Verdict
if recovery_q5 and recovery_q1:
    q5_wins_recovery = np.mean(recovery_q5) > np.mean(recovery_q1)
else:
    q5_wins_recovery = False
print(f"\nVerdict: {'Laggards rebound harder on recovery days — cheap convexity has merit' if q5_wins_recovery else 'Leaders outperform even on recovery days — S20 anti-laggard rule VALIDATED'}")

# Save all phase 2 results
phase2 = {
    "test2": test2,
    "test3": {"best_entry": best_entry, "spreads": test3_spreads,
              "quintiles": {f"Q{q}": {h: np.mean(q_horizon_results[q][h])*100 for h in horizons} for q in range(1,6)}},
    "test4": {
        "recovery": {"n": len(recovery_q1), "q1_avg": np.mean(recovery_q1)*100 if recovery_q1 else 0,
                     "q5_avg": np.mean(recovery_q5)*100 if recovery_q5 else 0},
        "continuation": {"n": len(continuation_q1), "q1_avg": np.mean(continuation_q1)*100 if continuation_q1 else 0,
                         "q5_avg": np.mean(continuation_q5)*100 if continuation_q5 else 0},
        "laggard_rebound": q5_wins_recovery
    }
}
with open(os.path.join(OUT_DIR, "phase2_results.json"), "w") as f:
    json.dump(phase2, f, indent=2, default=float)

print("\n✓ Phase 2 complete.")
