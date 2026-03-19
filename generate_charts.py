"""Generate charts for the backtest battery report."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import json, os

OUT_DIR = "backtest_output"

with open(os.path.join(OUT_DIR, "phase2_results.json")) as f:
    p2 = json.load(f)
with open(os.path.join(OUT_DIR, "phase3_results.json")) as f:
    p3 = json.load(f)

# Chart 1: Test 2 — Quintile AM vs PM returns (bar chart since scatter needs raw data)
fig, ax = plt.subplots(figsize=(8, 5))
quintiles = ["Q1\n(best)", "Q2", "Q3", "Q4", "Q5\n(worst)"]
am_vals = [p2["test2"]["quintiles"][f"Q{q}"]["avg_am"] for q in range(1, 6)]
pm_vals = [p2["test2"]["quintiles"][f"Q{q}"]["avg_pm"] for q in range(1, 6)]
x = np.arange(5)
ax.bar(x - 0.2, am_vals, 0.35, label="AM Return %", color="steelblue")
ax.bar(x + 0.2, pm_vals, 0.35, label="PM Return %", color="coral")
ax.set_xticks(x)
ax.set_xticklabels(quintiles)
ax.set_ylabel("Avg Return (%)")
ax.set_title("Test 2: AM Rank Quintile → PM Return (Stress Days)")
ax.legend()
ax.axhline(0, color="black", linewidth=0.5)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, "test2_am_pm_quintiles.png"), dpi=150)
plt.close()

# Chart 2: Test 3 — Quintile returns by horizon
fig, ax = plt.subplots(figsize=(8, 5))
horizons = ["1h", "2h", "EOD"]
for q in range(1, 6):
    vals = [p2["test3"]["quintiles"][f"Q{q}"][h] for h in horizons]
    label = f"Q{q}" + (" (best)" if q == 1 else " (worst)" if q == 5 else "")
    ax.plot(horizons, vals, marker="o", label=label)
ax.set_ylabel("Avg Forward Return (%)")
ax.set_title("Test 3: Forward Returns by Quintile & Horizon")
ax.legend()
ax.axhline(0, color="black", linewidth=0.5)
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, "test3_forward_returns.png"), dpi=150)
plt.close()

# Chart 3: Test 4 — Leader vs Laggard (Recovery vs Continuation)
fig, ax = plt.subplots(figsize=(7, 5))
categories = ["Recovery\nDays", "Continuation\nDays"]
q1_vals = [p2["test4"]["recovery"]["q1_avg"], p2["test4"]["continuation"]["q1_avg"]]
q5_vals = [p2["test4"]["recovery"]["q5_avg"], p2["test4"]["continuation"]["q5_avg"]]
x = np.arange(2)
ax.bar(x - 0.2, q1_vals, 0.35, label="Q1 (Leaders)", color="green", alpha=0.7)
ax.bar(x + 0.2, q5_vals, 0.35, label="Q5 (Laggards)", color="red", alpha=0.7)
ax.set_xticks(x)
ax.set_xticklabels(categories)
ax.set_ylabel("Avg PM Return (%)")
ax.set_title("Test 4: Leaders vs Laggards — Recovery vs Continuation")
ax.legend()
ax.axhline(0, color="black", linewidth=0.5)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, "test4_leader_laggard.png"), dpi=150)
plt.close()

# Chart 4: Test 7 — Power Analysis
fig, ax = plt.subplots(figsize=(8, 5))
tests = ["T2:RS", "T3:Fwd", "T4:Lag", "T5:Sec", "T6:Def", "T8:Beta", "T9:VIXY"]
actual = [55, 55, 55, 55, 55, 55, 55]
required = [5, 7, 6, 88, 88, 9, 88]
colors = ["green" if a >= r else "orange" for a, r in zip(actual, required)]
x = np.arange(len(tests))
ax.barh(x, actual, color=colors, alpha=0.7, label="Actual N")
ax.barh(x, required, color="none", edgecolor="black", linestyle="--", label="Required N")
ax.set_yticks(x)
ax.set_yticklabels(tests)
ax.set_xlabel("Number of Stress Days")
ax.set_title("Test 7: Power Analysis — Actual vs Required Sample Size")
ax.legend()
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, "test7_power_analysis.png"), dpi=150)
plt.close()

print("✓ All 4 charts saved to backtest_output/")
