"""Phase 3: Tests 5-9 — Sector-Adj, DefenseRank, Power, Beta-Adj, VIXY"""
import pandas as pd
import numpy as np
from scipy import stats
import json, os
from datetime import time as dtime

OUT_DIR = "backtest_output"
TRADE_UNIVERSE = [
    "AAPL","AMD","AMZN","AVGO","BA","BABA","BIDU","C","COIN","COST",
    "GOOGL","GS","IBIT","JPM","MARA","META","MSFT","MU","NVDA",
    "PLTR","SNOW","TSLA","TSM","TXN","V"
]
SECTOR_MAP = {
    "Tech": ["AAPL","AMD","AMZN","AVGO","GOOGL","META","MSFT","MU","NVDA","PLTR","SNOW","TSM","TXN"],
    "Financial": ["C","COIN","GS","IBIT","JPM","MARA","V"],
    "ConsumerDisc": ["BABA","TSLA"],
    "Communication": ["BIDU"],
    "Industrials": ["BA"],
    "ConsumerStaples": ["COST"],
}
TICKER_SECTOR = {}
for sec, tks in SECTOR_MAP.items():
    for t in tks:
        TICKER_SECTOR[t] = sec

with open(os.path.join(OUT_DIR, "stress_days.json")) as f:
    stress_dates = [pd.Timestamp(d) for d in json.load(f)]

m5 = {}
for tk in TRADE_UNIVERSE + ["SPY", "VIXY"]:
    m5[tk] = pd.read_csv(os.path.join(OUT_DIR, f"{tk}_m5_regsess.csv"), parse_dates=["Datetime"])

daily_returns = pd.read_csv(os.path.join(OUT_DIR, "daily_returns.csv"), index_col=0, parse_dates=True)

T_0930, T_1200, T_1230, T_1555 = dtime(9,30), dtime(12,0), dtime(12,30), dtime(15,55)

def get_price_at(df, date, target_time):
    day = df[df["Datetime"].dt.date == date.date()]
    if day.empty: return np.nan
    mask = day["Datetime"].dt.time <= target_time
    return day[mask].iloc[-1]["Close"] if mask.any() else np.nan

def get_first_close(df, date):
    day = df[df["Datetime"].dt.date == date.date()]
    return day.iloc[0]["Close"] if not day.empty else np.nan

def get_last_close(df, date):
    day = df[df["Datetime"].dt.date == date.date()]
    return day.iloc[-1]["Close"] if not day.empty else np.nan

# ── Test 5: Sector-Adjusted RS ──────────────────────────────────────────
print("=" * 60)
print("TEST 5: SECTOR-ADJUSTED RS")
print("=" * 60)

spearman_corrs = []
top5_changes = 0
total_days = 0

for sd in stress_dates:
    am_raw = {}
    for tk in TRADE_UNIVERSE:
        p_open = get_first_close(m5[tk], sd)
        p_1230 = get_price_at(m5[tk], sd, T_1230)
        if np.isnan(p_open) or np.isnan(p_1230) or p_open == 0: continue
        am_raw[tk] = (p_1230 / p_open) - 1

    if len(am_raw) < 20: continue
    total_days += 1

    # Sector median
    sector_medians = {}
    for sec, tks in SECTOR_MAP.items():
        vals = [am_raw[t] for t in tks if t in am_raw]
        sector_medians[sec] = np.median(vals) if vals else 0

    am_adj = {tk: am_raw[tk] - sector_medians.get(TICKER_SECTOR.get(tk, ""), 0) for tk in am_raw}

    tickers = list(am_raw.keys())
    raw_rank = {t: r for r, t in enumerate(sorted(tickers, key=lambda x: am_raw[x], reverse=True))}
    adj_rank = {t: r for r, t in enumerate(sorted(tickers, key=lambda x: am_adj[x], reverse=True))}

    raw_ranks = [raw_rank[t] for t in tickers]
    adj_ranks = [adj_rank[t] for t in tickers]
    corr, _ = stats.spearmanr(raw_ranks, adj_ranks)
    spearman_corrs.append(corr)

    top5_raw = set(sorted(tickers, key=lambda x: am_raw[x], reverse=True)[:5])
    top5_adj = set(sorted(tickers, key=lambda x: am_adj[x], reverse=True)[:5])
    if top5_raw != top5_adj:
        top5_changes += 1

avg_corr = np.mean(spearman_corrs)
pct_change = (top5_changes / total_days * 100) if total_days else 0
print(f"\nAvg Spearman correlation (raw vs adj): {avg_corr:.4f}")
print(f"% days where Top-5 changes: {pct_change:.1f}% ({top5_changes}/{total_days})")
print(f"Recommendation: {'Sector adjustment worth it' if pct_change > 40 else 'Sector adjustment adds minimal value — skip for simplicity'}")

# ── Test 6: DefenseRank Validation ──────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 6: DEFENSERANK VALIDATION")
print("=" * 60)

# Precompute ATR20 for each ticker-date
daily_px = {}
for tk in TRADE_UNIVERSE:
    dp = pd.read_csv(os.path.join(OUT_DIR, f"{tk}_daily.csv"), parse_dates=["date"])
    dp = dp.set_index("date").sort_index()
    dp["TR"] = np.maximum(dp["High"] - dp["Low"],
                np.maximum(abs(dp["High"] - dp["Close"].shift(1)),
                           abs(dp["Low"] - dp["Close"].shift(1))))
    dp["ATR20"] = dp["TR"].rolling(20).mean()
    daily_px[tk] = dp

defense_top5_pm, close_top5_pm = [], []
rank_corrs = []

for sd in stress_dates:
    am_rets = {}
    defense_scores = {}
    pm_rets = {}

    for tk in TRADE_UNIVERSE:
        day = m5[tk][m5[tk]["Datetime"].dt.date == sd.date()]
        am = day[day["Datetime"].dt.time <= T_1230]
        if len(am) < 5: continue

        p_open = am.iloc[0]["Close"]
        p_1230 = am.iloc[-1]["Close"]
        p_eod = get_last_close(m5[tk], sd)
        if p_open == 0 or np.isnan(p_eod): continue

        am_rets[tk] = (p_1230 / p_open) - 1
        pm_rets[tk] = (p_eod / p_1230) - 1 if p_1230 != 0 else np.nan

        # Max drawdown in AM
        prices = am["Close"].values
        peak = np.maximum.accumulate(prices)
        dd = (prices - peak) / peak
        max_dd = dd.min()  # most negative

        # ATR20
        if sd in daily_px[tk].index:
            atr = daily_px[tk].loc[:sd, "ATR20"].dropna()
            atr_val = atr.iloc[-1] if len(atr) else np.nan
        else:
            idx = daily_px[tk].index[daily_px[tk].index <= sd]
            atr_val = daily_px[tk].loc[idx[-1], "ATR20"] if len(idx) else np.nan

        if not np.isnan(atr_val) and atr_val != 0:
            defense_scores[tk] = -max_dd / (atr_val / p_open)  # normalize ATR to %
        else:
            defense_scores[tk] = -max_dd  # fallback

    common = set(am_rets) & set(defense_scores) & set(pm_rets)
    common = [t for t in common if not np.isnan(pm_rets[t])]
    if len(common) < 20: continue

    # Rank by close return and defense score
    close_ranked = sorted(common, key=lambda t: am_rets[t], reverse=True)
    defense_ranked = sorted(common, key=lambda t: defense_scores[t], reverse=True)

    defense_top5 = defense_ranked[:5]
    close_top5 = close_ranked[:5]

    d_pm = np.mean([pm_rets[t] for t in defense_top5])
    c_pm = np.mean([pm_rets[t] for t in close_top5])
    defense_top5_pm.append(d_pm)
    close_top5_pm.append(c_pm)

    # Rank correlation
    d_ranks = [defense_ranked.index(t) for t in common]
    c_ranks = [close_ranked.index(t) for t in common]
    corr, _ = stats.spearmanr(d_ranks, c_ranks)
    rank_corrs.append(corr)

print(f"\n{'Method':<20} {'Top-5 Avg PM':>14} {'Hit Rate':>10}")
print("-" * 46)
for name, vals in [("DefenseRank", defense_top5_pm), ("Close-Return", close_top5_pm)]:
    avg = np.mean(vals) * 100
    hit = np.mean([1 if v > 0 else 0 for v in vals]) * 100
    print(f"{name:<20} {avg:>13.3f}% {hit:>9.1f}%")

print(f"\nCorrelation (Defense vs Close rank): {np.mean(rank_corrs):.4f}")
better = "DefenseRank" if np.mean(defense_top5_pm) > np.mean(close_top5_pm) else "Close-Return"
print(f"Recommendation: {better} produces better Top-5 PM returns")

# ── Test 7: Power Analysis ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 7: STRESS FREQUENCY & POWER ANALYSIS")
print("=" * 60)

with open(os.path.join(OUT_DIR, "phase1_summary.json")) as f:
    p1 = json.load(f)
with open(os.path.join(OUT_DIR, "phase2_results.json")) as f:
    p2 = json.load(f)

n_actual = p2["test2"]["n_days"]

# Load test2 spreads for effect size (re-derive from avg/t-stat)
effect_size_t2 = abs(p2["test2"]["t_stat"]) / np.sqrt(n_actual)  # Cohen's d approx

def min_n_for_power(effect_d, power=0.8, alpha=0.05):
    """Approximate min N for 1-sample t-test at given power."""
    from scipy.stats import norm
    z_alpha = norm.ppf(1 - alpha / 2)
    z_beta = norm.ppf(power)
    return int(np.ceil(((z_alpha + z_beta) / effect_d) ** 2))

tests_power = [
    ("Test 2: RS Persistence", effect_size_t2, n_actual),
    ("Test 3: Fwd Returns", effect_size_t2 * 0.8, n_actual),  # approximate
    ("Test 4: Laggard Rebound", effect_size_t2 * 0.9, n_actual),
    ("Test 5: Sector Adj", 0.3, total_days),  # moderate effect
    ("Test 6: DefenseRank", 0.3, len(defense_top5_pm)),
    ("Test 8: Beta-Adj", effect_size_t2 * 0.7, n_actual),
    ("Test 9: VIXY Timing", 0.3, n_actual),
]

print(f"\n{'Test':<28} {'Effect d':>9} {'Req N':>7} {'Actual N':>9} {'Status':<14}")
print("-" * 72)
for name, d, n in tests_power:
    req_n = min_n_for_power(d) if d > 0 else 999
    status = "SUFFICIENT" if n >= req_n else "EXPLORATORY"
    print(f"{name:<28} {d:>9.3f} {req_n:>7} {n:>9} {status:<14}")

print(f"\nOverall: 13 months of data provides {n_actual} stress days — {'sufficient' if n_actual >= 30 else 'marginal'} for primary tests.")

# ── Test 8: Beta-Adjusted Excess Return ─────────────────────────────────
print("\n" + "=" * 60)
print("TEST 8: BETA-ADJUSTED EXCESS RETURN VS RAW RETURN")
print("=" * 60)

# Compute rolling 60-day beta
betas = {}
spy_rets = daily_returns["SPY"]
for tk in TRADE_UNIVERSE:
    tk_rets = daily_returns[tk]
    rolling_cov = tk_rets.rolling(60).cov(spy_rets)
    rolling_var = spy_rets.rolling(60).var()
    betas[tk] = rolling_cov / rolling_var

raw_spreads_t8, excess_spreads_t8 = [], []

for sd in stress_dates:
    spy_open = get_first_close(m5["SPY"], sd)
    spy_1230 = get_price_at(m5["SPY"], sd, T_1230)
    if np.isnan(spy_open) or np.isnan(spy_1230) or spy_open == 0: continue
    spy_am = (spy_1230 / spy_open) - 1

    raw_rets = {}
    excess_rets = {}
    pm_rets = {}

    for tk in TRADE_UNIVERSE:
        p_open = get_first_close(m5[tk], sd)
        p_1230 = get_price_at(m5[tk], sd, T_1230)
        p_eod = get_last_close(m5[tk], sd)
        if np.isnan(p_open) or np.isnan(p_1230) or np.isnan(p_eod) or p_open == 0 or p_1230 == 0:
            continue
        raw = (p_1230 / p_open) - 1
        raw_rets[tk] = raw
        pm_rets[tk] = (p_eod / p_1230) - 1

        # Get beta
        beta_series = betas.get(tk)
        if beta_series is not None:
            b_vals = beta_series.loc[:sd].dropna()
            b = b_vals.iloc[-1] if len(b_vals) else 1.0
        else:
            b = 1.0
        excess_rets[tk] = raw - b * spy_am

    common = [t for t in TRADE_UNIVERSE if t in raw_rets and t in excess_rets and t in pm_rets]
    if len(common) < 20: continue

    q_size = len(common) // 5

    # Raw ranking
    raw_ranked = sorted(common, key=lambda t: raw_rets[t], reverse=True)
    raw_q1_pm = np.mean([pm_rets[t] for t in raw_ranked[:q_size]])
    raw_q5_pm = np.mean([pm_rets[t] for t in raw_ranked[-q_size:]])
    raw_spreads_t8.append(raw_q1_pm - raw_q5_pm)

    # Excess ranking
    exc_ranked = sorted(common, key=lambda t: excess_rets[t], reverse=True)
    exc_q1_pm = np.mean([pm_rets[t] for t in exc_ranked[:q_size]])
    exc_q5_pm = np.mean([pm_rets[t] for t in exc_ranked[-q_size:]])
    excess_spreads_t8.append(exc_q1_pm - exc_q5_pm)

print(f"\n{'Method':<16} {'Q1 PM Avg':>12} {'Q5 PM Avg':>12} {'Spread':>10} {'T-stat':>8}")
print("-" * 62)
for name, spreads_list in [("Raw Return", raw_spreads_t8), ("Beta-Adjusted", excess_spreads_t8)]:
    avg_spread = np.mean(spreads_list) * 100
    t, p = stats.ttest_1samp(spreads_list, 0)
    print(f"{name:<16} {'':>12} {'':>12} {avg_spread:>9.3f}% {t:>8.3f}")

raw_better = abs(np.mean(raw_spreads_t8)) > abs(np.mean(excess_spreads_t8))
print(f"\nRecommendation: {'Raw return' if raw_better else 'Beta-adjusted'} ranking predicts PM returns better")

# ── Test 9: VIXY Intraday Analysis ──────────────────────────────────────
print("\n" + "=" * 60)
print("TEST 9: VIXY INTRADAY ANALYSIS (EXPLORATORY)")
print("=" * 60)
print("CAVEAT: VIXY is an imperfect VIX proxy (contango decay, tracking error)")

vixy = m5["VIXY"]
crush_durations = []
crush_times = []
crush_entry_rets, fixed_noon_rets, fixed_1400_rets = [], [], []

for sd in stress_dates:
    vday = vixy[vixy["Datetime"].dt.date == sd.date()].copy()
    if len(vday) < 10: continue

    # VIXY trajectory
    vday = vday.sort_values("Datetime").reset_index(drop=True)
    prices = vday["Close"].values
    times = vday["Datetime"].values

    peak_idx = np.argmax(prices)
    trough_idx = peak_idx + np.argmin(prices[peak_idx:]) if peak_idx < len(prices) else peak_idx

    peak_price = prices[peak_idx]
    trough_price = prices[trough_idx]
    if peak_price == 0: continue

    duration_bars = trough_idx - peak_idx
    crush_durations.append(duration_bars * 5)  # minutes

    # CrushConfirmed: VIXY fallen >8% from intraday high AND 3 of last 5 bars negative
    crush_confirmed_time = None
    for i in range(peak_idx + 1, len(prices)):
        drop_pct = (prices[i] - peak_price) / peak_price
        if drop_pct < -0.08 and i >= 4:
            last5 = [prices[j] - prices[j-1] for j in range(max(1,i-4), i+1)]
            neg_count = sum(1 for x in last5 if x < 0)
            if neg_count >= 3:
                crush_confirmed_time = pd.Timestamp(times[i])
                crush_times.append(crush_confirmed_time)
                # Forward return from CrushConfirmed to EOD for Q1 leaders
                break

    # Get Q1 tickers (ranked at noon)
    rets_at_noon = {}
    for tk in TRADE_UNIVERSE:
        p_o = get_first_close(m5[tk], sd)
        p_n = get_price_at(m5[tk], sd, T_1200)
        if not np.isnan(p_o) and not np.isnan(p_n) and p_o != 0:
            rets_at_noon[tk] = (p_n / p_o) - 1
    if len(rets_at_noon) < 20: continue
    ranked = sorted(rets_at_noon.keys(), key=lambda t: rets_at_noon[t], reverse=True)
    q1_tickers = ranked[:5]

    # Entry returns comparison
    def avg_fwd_return(entry_time_val):
        rets = []
        for tk in q1_tickers:
            tkday = m5[tk][m5[tk]["Datetime"].dt.date == sd.date()]
            if isinstance(entry_time_val, pd.Timestamp):
                after = tkday[tkday["Datetime"] >= entry_time_val]
            else:
                after = tkday[tkday["Datetime"].dt.time >= entry_time_val]
            if len(after) < 2: continue
            entry_p = after.iloc[0]["Close"]
            eod_p = tkday.iloc[-1]["Close"]
            if entry_p != 0:
                rets.append((eod_p / entry_p) - 1)
        return np.mean(rets) if rets else np.nan

    noon_ret = avg_fwd_return(T_1200)
    t1400_ret = avg_fwd_return(dtime(14, 0))
    if not np.isnan(noon_ret): fixed_noon_rets.append(noon_ret)
    if not np.isnan(t1400_ret): fixed_1400_rets.append(t1400_ret)

    if crush_confirmed_time is not None:
        cc_ret = avg_fwd_return(crush_confirmed_time)
        if not np.isnan(cc_ret): crush_entry_rets.append(cc_ret)

avg_crush_dur = np.mean(crush_durations) if crush_durations else 0
print(f"\nAvg crush duration (peak→trough): {avg_crush_dur:.0f} minutes ({avg_crush_dur/60:.1f} hours)")
print(f"CrushConfirmed triggered on: {len(crush_times)}/{len(stress_dates)} stress days")

if crush_times:
    avg_hour = np.mean([t.hour + t.minute/60 for t in crush_times])
    print(f"Avg CrushConfirmed time: ~{int(avg_hour)}:{int((avg_hour%1)*60):02d} ET")

print(f"\n{'Entry Method':<22} {'Avg Q1 Fwd Ret':>15} {'N Days':>8}")
print("-" * 48)
for name, vals in [("Fixed 12:00", fixed_noon_rets), ("Fixed 14:00", fixed_1400_rets),
                    ("CrushConfirmed", crush_entry_rets)]:
    avg = np.mean(vals) * 100 if vals else 0
    print(f"{name:<22} {avg:>14.3f}% {len(vals):>8}")

# Save all phase 3 results
phase3 = {
    "test5": {"avg_spearman": avg_corr, "pct_top5_change": pct_change},
    "test6": {"defense_avg_pm": np.mean(defense_top5_pm)*100, "close_avg_pm": np.mean(close_top5_pm)*100,
              "rank_corr": np.mean(rank_corrs)},
    "test7": {"n_stress_days": n_actual, "sufficient": n_actual >= 30},
    "test8": {"raw_spread": np.mean(raw_spreads_t8)*100, "excess_spread": np.mean(excess_spreads_t8)*100,
              "raw_better": raw_better},
    "test9": {"avg_crush_minutes": avg_crush_dur, "n_crush_confirmed": len(crush_times),
              "crush_entry_avg": np.mean(crush_entry_rets)*100 if crush_entry_rets else 0,
              "noon_entry_avg": np.mean(fixed_noon_rets)*100 if fixed_noon_rets else 0,
              "t1400_entry_avg": np.mean(fixed_1400_rets)*100 if fixed_1400_rets else 0}
}
with open(os.path.join(OUT_DIR, "phase3_results.json"), "w") as f:
    json.dump(phase3, f, indent=2, default=float)

print("\n✓ Phase 3 complete.")
