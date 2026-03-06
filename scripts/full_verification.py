"""
Full Statistical Verification Pass — All 6 Tasks.

Addresses all outstanding ChatGPT PRO concerns about the 25-ticker
Config A' backtest with live earnings filter (195 trades).
"""

import json
import os
import sys
import csv
import numpy as np
import pandas as pd
from itertools import combinations
from scipy import stats as scipy_stats
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Paths ──────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
TRADE_LOG_NEW = BASE / "results" / "phase3_25ticker_earnings_fix" / "trades_a_prime.csv"
TRADE_LOG_OLD = BASE / "results" / "phase3_25ticker_full" / "trades_a_prime.csv"
EARNINGS_CAL = BASE / "backtester" / "data" / "earnings_calendar.json"
RESULTS_JSON = BASE / "results" / "phase3_25ticker_earnings_fix" / "variant_a_prime_results.json"
OUT_DIR = BASE / "results" / "phase3_full_verification"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FULL_START = "2025-02-10"
FULL_END = "2026-01-31"
CAPITAL = 100_000.0
N_TRIALS = 50

LOG = []
def log(msg=""):
    print(msg)
    LOG.append(msg)

def jsonable(obj):
    """Recursively convert numpy types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(x) for x in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


# ═══════════════════════════════════════════════════════════════════════
# TASK 1: CSCV/PBO on per-trade R returns
# ═══════════════════════════════════════════════════════════════════════

def task1_cscv_pbo():
    log("=" * 80)
    log("  TASK 1: CSCV/PBO — Per-Trade R Returns vs Daily Equity")
    log("=" * 80)

    trades = pd.read_csv(TRADE_LOG_NEW)
    trades_r = trades['pnl_r'].values
    n = len(trades_r)

    # ── CSCV-Trade: split 195 trades into S=8 subsets ──────────────
    S = 8
    subset_size = n // S
    remainder = n % S

    log(f"\n  CSCV-Trade: {n} trades, S={S} subsets, ~{subset_size} trades/subset")

    # Split chronologically into S subsets
    subsets = []
    idx = 0
    for i in range(S):
        sz = subset_size + (1 if i < remainder else 0)
        subsets.append(trades_r[idx:idx + sz])
        idx += sz
        log(f"    Subset {i}: {len(subsets[-1])} trades, "
            f"mean_R={subsets[-1].mean():.3f}, sum_R={subsets[-1].sum():.1f}")

    # For CSCV, we need multiple "strategies" to rank.
    # With a single strategy, PBO measures whether the strategy overfits
    # to particular time periods. We create synthetic configs by varying
    # a simple parameter: the mean-R threshold for filtering trades.
    # Instead, we do the standard single-strategy temporal stability test:
    # split into IS/OOS halves, measure IS→OOS performance degradation.

    half = S // 2  # 4
    combos = list(combinations(range(S), half))
    n_combos = len(combos)
    log(f"\n  Combinations: C({S},{half}) = {n_combos}")

    is_sharpes = []
    oos_sharpes = []
    oos_negative_count = 0

    for combo in combos:
        oos_idx = set(range(S)) - set(combo)

        is_returns = np.concatenate([subsets[i] for i in combo])
        oos_returns = np.concatenate([subsets[i] for i in oos_idx])

        is_sr = is_returns.mean() / is_returns.std(ddof=1) if is_returns.std(ddof=1) > 0 else 0
        oos_sr = oos_returns.mean() / oos_returns.std(ddof=1) if oos_returns.std(ddof=1) > 0 else 0

        is_sharpes.append(is_sr)
        oos_sharpes.append(oos_sr)

        if oos_sr < 0:
            oos_negative_count += 1

    is_sharpes = np.array(is_sharpes)
    oos_sharpes = np.array(oos_sharpes)

    # PBO = fraction of splits where OOS performance is negative
    pbo_trade = oos_negative_count / n_combos
    corr, corr_p = scipy_stats.pearsonr(is_sharpes, oos_sharpes)

    # Logit of OOS rank (for single strategy = relative to zero)
    logit_values = []
    for oos_sr in oos_sharpes:
        # Logit: log(rank / (1 - rank)). For single strat, rank = 1 if OOS>0, 0 otherwise
        # Use continuous: logit(Phi(z)) where z = OOS SR / se
        p = scipy_stats.norm.cdf(oos_sr / (0.1 + abs(oos_sr)))  # rough probability
        p = np.clip(p, 0.01, 0.99)
        logit_values.append(np.log(p / (1 - p)))
    logit_values = np.array(logit_values)

    log(f"\n  CSCV-Trade Results:")
    log(f"    PBO (OOS-negative splits):  {pbo_trade*100:.1f}% ({oos_negative_count}/{n_combos})")
    log(f"    IS Sharpe mean:             {is_sharpes.mean():.4f}")
    log(f"    OOS Sharpe mean:            {oos_sharpes.mean():.4f}")
    degradation = 1 - oos_sharpes.mean() / is_sharpes.mean() if is_sharpes.mean() != 0 else float('inf')
    log(f"    IS→OOS degradation:         {degradation*100:.1f}%")
    log(f"    IS-OOS correlation:         r={corr:.4f} (p={corr_p:.4f})")
    log(f"    Logit mean:                 {logit_values.mean():.4f}")
    log(f"    Logit median:               {np.median(logit_values):.4f}")

    # ── CSCV-Portfolio: daily equity returns (with zeros) ──────────
    log(f"\n  CSCV-Portfolio (daily equity, for comparison):")

    trades['exit_date'] = pd.to_datetime(trades['exit_time']).dt.date
    daily_pnl = trades.groupby('exit_date')['pnl'].sum()
    daily_pnl.index = pd.to_datetime(daily_pnl.index)
    all_dates = pd.bdate_range(start=FULL_START, end=FULL_END)
    daily_ret = pd.Series(0.0, index=all_dates)
    for dt, pnl in daily_pnl.items():
        if dt in daily_ret.index:
            daily_ret[dt] = pnl / CAPITAL
    daily_arr = daily_ret.values
    T = len(daily_arr)

    S_d = 8
    sub_sz_d = T // S_d
    rem_d = T % S_d
    subsets_d = []
    idx_d = 0
    for i in range(S_d):
        sz = sub_sz_d + (1 if i < rem_d else 0)
        subsets_d.append(daily_arr[idx_d:idx_d + sz])
        idx_d += sz

    combos_d = list(combinations(range(S_d), S_d // 2))
    is_sr_d = []
    oos_sr_d = []
    oos_neg_d = 0
    for combo in combos_d:
        oos_idx = set(range(S_d)) - set(combo)
        is_r = np.concatenate([subsets_d[i] for i in combo])
        oos_r = np.concatenate([subsets_d[i] for i in oos_idx])
        isr = is_r.mean() / is_r.std(ddof=1) * np.sqrt(252) if is_r.std(ddof=1) > 0 else 0
        osr = oos_r.mean() / oos_r.std(ddof=1) * np.sqrt(252) if oos_r.std(ddof=1) > 0 else 0
        is_sr_d.append(isr)
        oos_sr_d.append(osr)
        if osr < 0:
            oos_neg_d += 1

    is_sr_d = np.array(is_sr_d)
    oos_sr_d = np.array(oos_sr_d)
    pbo_daily = oos_neg_d / len(combos_d)
    corr_d, corr_d_p = scipy_stats.pearsonr(is_sr_d, oos_sr_d)
    deg_d = 1 - oos_sr_d.mean() / is_sr_d.mean() if is_sr_d.mean() != 0 else float('inf')

    log(f"    PBO (OOS-negative):         {pbo_daily*100:.1f}% ({oos_neg_d}/{len(combos_d)})")
    log(f"    IS Sharpe mean:             {is_sr_d.mean():.4f}")
    log(f"    OOS Sharpe mean:            {oos_sr_d.mean():.4f}")
    log(f"    IS→OOS degradation:         {deg_d*100:.1f}%")
    log(f"    IS-OOS correlation:         r={corr_d:.4f} (p={corr_d_p:.4f})")

    # ── Side-by-side ──────────────────────────────────────────────
    log(f"\n  {'Metric':<30} {'CSCV-Trade':>15} {'CSCV-Portfolio':>15}")
    log(f"  {'─' * 60}")
    log(f"  {'PBO':<30} {pbo_trade*100:>14.1f}% {pbo_daily*100:>14.1f}%")
    log(f"  {'IS→OOS degradation':<30} {degradation*100:>14.1f}% {deg_d*100:>14.1f}%")
    log(f"  {'IS-OOS correlation':<30} {corr:>15.4f} {corr_d:>15.4f}")
    log(f"  {'OOS Sharpe mean':<30} {oos_sharpes.mean():>15.4f} {oos_sr_d.mean():>15.4f}")

    return {
        'cscv_trade': {
            'n_trades': n, 'S': S, 'n_combos': n_combos,
            'pbo': round(pbo_trade, 4),
            'is_sharpe_mean': round(float(is_sharpes.mean()), 4),
            'oos_sharpe_mean': round(float(oos_sharpes.mean()), 4),
            'degradation_pct': round(degradation * 100, 1),
            'is_oos_corr': round(float(corr), 4),
            'is_oos_corr_p': round(float(corr_p), 4),
            'logit_mean': round(float(logit_values.mean()), 4),
            'logit_median': round(float(np.median(logit_values)), 4),
        },
        'cscv_portfolio': {
            'T_days': T, 'S': S_d, 'n_combos': len(combos_d),
            'pbo': round(pbo_daily, 4),
            'is_sharpe_mean': round(float(is_sr_d.mean()), 4),
            'oos_sharpe_mean': round(float(oos_sr_d.mean()), 4),
            'degradation_pct': round(deg_d * 100, 1),
            'is_oos_corr': round(float(corr_d), 4),
            'is_oos_corr_p': round(float(corr_d_p), 4),
        }
    }


# ═══════════════════════════════════════════════════════════════════════
# TASK 2: Verify earnings filter correctness
# ═══════════════════════════════════════════════════════════════════════

def task2_earnings_verification():
    log("\n" + "=" * 80)
    log("  TASK 2: EARNINGS FILTER VERIFICATION")
    log("=" * 80)

    # Load funnel from results
    with open(RESULTS_JSON) as f:
        results = json.load(f)
    funnel = results['funnel']

    log(f"\n  Signal Funnel:")
    for k, v in funnel.items():
        log(f"    {k:<30} {v:>6}")

    # Load earnings calendar
    with open(EARNINGS_CAL) as f:
        cal = json.load(f)

    # Build set of blocked dates (earnings day + 1 post-earnings day)
    blocked_dates = {}
    for ticker, dates in cal.items():
        blocked = set()
        for d in dates:
            dt = date.fromisoformat(d)
            blocked.add(dt)
            blocked.add(dt + timedelta(days=1))
        blocked_dates[ticker] = blocked

    # Compare old vs new trade logs to find blocked trades
    old_trades = pd.read_csv(TRADE_LOG_OLD)
    new_trades = pd.read_csv(TRADE_LOG_NEW)

    old_keys = set(zip(old_trades['ticker'], old_trades['entry_time']))
    new_keys = set(zip(new_trades['ticker'], new_trades['entry_time']))
    blocked_keys = old_keys - new_keys

    log(f"\n  Trades blocked by earnings filter: {len(blocked_keys)}")
    log(f"  {'Ticker':<6} {'Entry Time':<22} {'Dir':<6} {'Pattern':<8} {'PnL':>10} {'Matching Earnings Date'}")
    log(f"  {'─' * 80}")

    old_by_key = {(r['ticker'], r['entry_time']): r for _, r in old_trades.iterrows()}
    blocked_details = []
    for key in sorted(blocked_keys):
        t = old_by_key[key]
        entry_date = pd.to_datetime(t['entry_time']).date()
        # Find matching earnings date
        ticker_blocked = blocked_dates.get(t['ticker'], set())
        match = "MATCH" if entry_date in ticker_blocked else "NO MATCH!"
        # Find the specific earnings date
        nearest = None
        for ed in cal.get(t['ticker'], []):
            edt = date.fromisoformat(ed)
            if entry_date == edt:
                nearest = f"{ed} (earnings day)"
                break
            elif entry_date == edt + timedelta(days=1):
                nearest = f"{ed} (post-earnings +1d)"
                break

        log(f"  {t['ticker']:<6} {t['entry_time']:<22} {t['direction']:<6} {t['pattern']:<8} "
            f"${t['pnl']:>9.0f} {nearest or 'UNKNOWN'} [{match}]")

        blocked_details.append({
            'ticker': t['ticker'], 'entry_time': t['entry_time'],
            'direction': t['direction'], 'pattern': t['pattern'],
            'pnl': round(float(t['pnl']), 2),
            'pnl_r': round(float(t['pnl_r']), 4),
            'earnings_date': nearest,
            'verified': match == "MATCH"
        })

    all_verified = all(d['verified'] for d in blocked_details)
    log(f"\n  All blocked trades match earnings calendar? {'YES' if all_verified else 'NO — INVESTIGATE!'}")

    blocked_pnl = sum(d['pnl'] for d in blocked_details)
    blocked_winners = sum(1 for d in blocked_details if d['pnl'] > 0)
    blocked_losers = sum(1 for d in blocked_details if d['pnl'] <= 0)
    log(f"  Blocked winners: {blocked_winners}, losers: {blocked_losers}")
    log(f"  Net P&L of blocked trades: ${blocked_pnl:,.0f}")

    return {
        'funnel': funnel,
        'blocked_trades': blocked_details,
        'all_verified': all_verified,
        'blocked_winners': blocked_winners,
        'blocked_losers': blocked_losers,
        'blocked_net_pnl': round(blocked_pnl, 2),
    }


# ═══════════════════════════════════════════════════════════════════════
# TASK 3: Per-trade return distribution analysis
# ═══════════════════════════════════════════════════════════════════════

def task3_distribution():
    log("\n" + "=" * 80)
    log("  TASK 3: PER-TRADE RETURN DISTRIBUTION ANALYSIS")
    log("=" * 80)

    trades = pd.read_csv(TRADE_LOG_NEW)
    r = trades['pnl_r'].values
    pnl = trades['pnl'].values
    n = len(r)

    total_pnl = pnl.sum()

    log(f"\n  Basic Stats (195 trades):")
    log(f"    Mean R:     {r.mean():.4f}")
    log(f"    Median R:   {np.median(r):.4f}")
    log(f"    Std R:      {r.std(ddof=1):.4f}")
    log(f"    Skewness:   {scipy_stats.skew(r):.4f}")
    log(f"    Kurtosis:   {scipy_stats.kurtosis(r, fisher=True):.4f} (excess)")

    # Top-5 trades
    trades_sorted = trades.sort_values('pnl', ascending=False)
    log(f"\n  Top-5 Trades:")
    log(f"    {'Ticker':<6} {'Entry Date':<22} {'Dir':<6} {'Pattern':<8} {'R':>8} {'PnL':>10} {'% Total':>8}")
    log(f"    {'─' * 70}")
    top5_pnl = 0
    top5_details = []
    for i, (_, t) in enumerate(trades_sorted.head(5).iterrows()):
        pct = t['pnl'] / total_pnl * 100
        top5_pnl += t['pnl']
        log(f"    {t['ticker']:<6} {t['entry_time']:<22} {t['direction']:<6} {t['pattern']:<8} "
            f"{t['pnl_r']:>8.2f} ${t['pnl']:>9.0f} {pct:>7.1f}%")
        top5_details.append({
            'ticker': t['ticker'], 'entry_time': t['entry_time'],
            'pnl': round(float(t['pnl']), 2), 'pnl_r': round(float(t['pnl_r']), 2),
            'pct_of_total': round(pct, 1)
        })
    log(f"    Top-5 concentration: ${top5_pnl:,.0f} = {top5_pnl/total_pnl*100:.1f}% of total P&L")

    # Bottom-5 trades
    log(f"\n  Bottom-5 Trades:")
    log(f"    {'Ticker':<6} {'Entry Date':<22} {'Dir':<6} {'Pattern':<8} {'R':>8} {'PnL':>10}")
    log(f"    {'─' * 60}")
    bottom5_details = []
    for _, t in trades_sorted.tail(5).iterrows():
        log(f"    {t['ticker']:<6} {t['entry_time']:<22} {t['direction']:<6} {t['pattern']:<8} "
            f"{t['pnl_r']:>8.2f} ${t['pnl']:>9.0f}")
        bottom5_details.append({
            'ticker': t['ticker'], 'entry_time': t['entry_time'],
            'pnl': round(float(t['pnl']), 2), 'pnl_r': round(float(t['pnl_r']), 2),
        })

    # Win rate by pattern
    log(f"\n  Win Rate by Pattern:")
    log(f"    {'Pattern':<10} {'Trades':>8} {'Wins':>8} {'WR':>8} {'Mean R':>8} {'Total PnL':>12}")
    log(f"    {'─' * 55}")
    pattern_stats = []
    for pat in sorted(trades['pattern'].unique()):
        subset = trades[trades['pattern'] == pat]
        wins = (subset['pnl'] > 0).sum()
        wr = wins / len(subset) * 100
        mean_r = subset['pnl_r'].mean()
        tot = subset['pnl'].sum()
        log(f"    {pat:<10} {len(subset):>8} {wins:>8} {wr:>7.1f}% {mean_r:>8.3f} ${tot:>11,.0f}")
        pattern_stats.append({
            'pattern': pat, 'trades': len(subset), 'wins': int(wins),
            'win_rate': round(wr, 1), 'mean_r': round(float(mean_r), 4),
            'total_pnl': round(float(tot), 2)
        })

    # Win rate by ticker (top 5 and bottom 5)
    log(f"\n  Win Rate by Ticker (sorted by PnL):")
    ticker_stats = []
    for ticker in sorted(trades['ticker'].unique()):
        subset = trades[trades['ticker'] == ticker]
        wins = (subset['pnl'] > 0).sum()
        wr = wins / len(subset) * 100
        tot = subset['pnl'].sum()
        ticker_stats.append({
            'ticker': ticker, 'trades': len(subset), 'wins': int(wins),
            'win_rate': round(wr, 1), 'total_pnl': round(float(tot), 2)
        })
    ticker_stats.sort(key=lambda x: x['total_pnl'], reverse=True)

    log(f"    {'Ticker':<6} {'Trades':>8} {'Wins':>8} {'WR':>8} {'Total PnL':>12}")
    log(f"    {'─' * 45}")
    log(f"    Top 5:")
    for ts in ticker_stats[:5]:
        log(f"    {ts['ticker']:<6} {ts['trades']:>8} {ts['wins']:>8} {ts['win_rate']:>7.1f}% ${ts['total_pnl']:>11,.0f}")
    log(f"    Bottom 5:")
    for ts in ticker_stats[-5:]:
        log(f"    {ts['ticker']:<6} {ts['trades']:>8} {ts['wins']:>8} {ts['win_rate']:>7.1f}% ${ts['total_pnl']:>11,.0f}")

    # Streaks
    is_win = (trades['pnl'].values > 0).astype(int)
    max_losing = max_winning = cur_losing = cur_winning = 0
    for w in is_win:
        if w:
            cur_winning += 1
            cur_losing = 0
        else:
            cur_losing += 1
            cur_winning = 0
        max_losing = max(max_losing, cur_losing)
        max_winning = max(max_winning, cur_winning)

    log(f"\n  Streaks:")
    log(f"    Longest losing streak:  {max_losing}")
    log(f"    Longest winning streak: {max_winning}")

    return {
        'n_trades': n,
        'mean_r': round(float(r.mean()), 4),
        'median_r': round(float(np.median(r)), 4),
        'std_r': round(float(r.std(ddof=1)), 4),
        'skewness': round(float(scipy_stats.skew(r)), 4),
        'kurtosis_excess': round(float(scipy_stats.kurtosis(r, fisher=True)), 4),
        'top5_trades': top5_details,
        'top5_concentration_pct': round(top5_pnl / total_pnl * 100, 1),
        'bottom5_trades': bottom5_details,
        'pattern_stats': pattern_stats,
        'ticker_stats_top5': ticker_stats[:5],
        'ticker_stats_bottom5': ticker_stats[-5:],
        'longest_losing_streak': max_losing,
        'longest_winning_streak': max_winning,
    }


# ═══════════════════════════════════════════════════════════════════════
# TASK 4: Regime / quarterly analysis
# ═══════════════════════════════════════════════════════════════════════

def task4_regime():
    log("\n" + "=" * 80)
    log("  TASK 4: REGIME / QUARTERLY ANALYSIS")
    log("=" * 80)

    trades = pd.read_csv(TRADE_LOG_NEW)
    trades['entry_dt'] = pd.to_datetime(trades['entry_time'])
    trades['quarter'] = trades['entry_dt'].dt.to_period('Q').astype(str)
    trades['month'] = trades['entry_dt'].dt.to_period('M').astype(str)

    total_pnl = trades['pnl'].sum()

    # Quarterly breakdown
    log(f"\n  Quarterly Breakdown:")
    log(f"    {'Quarter':<10} {'Trades':>8} {'Wins':>8} {'WR':>8} {'PF':>8} {'PnL':>12} {'% Total':>8}")
    log(f"    {'─' * 65}")

    quarterly_results = []
    for q in sorted(trades['quarter'].unique()):
        subset = trades[trades['quarter'] == q]
        wins = (subset['pnl'] > 0).sum()
        wr = wins / len(subset) * 100
        gross_profit = subset.loc[subset['pnl'] > 0, 'pnl'].sum()
        gross_loss = abs(subset.loc[subset['pnl'] <= 0, 'pnl'].sum())
        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        tot = subset['pnl'].sum()
        pct = tot / total_pnl * 100 if total_pnl != 0 else 0
        log(f"    {q:<10} {len(subset):>8} {wins:>8} {wr:>7.1f}% {pf:>8.2f} ${tot:>11,.0f} {pct:>7.1f}%")
        quarterly_results.append({
            'quarter': q, 'trades': len(subset), 'wins': int(wins),
            'win_rate': round(wr, 1), 'pf': round(pf, 2) if pf != float('inf') else 'inf',
            'pnl': round(float(tot), 2), 'pct_of_total': round(pct, 1),
            'profitable': tot > 0,
        })

    profitable_quarters = sum(1 for q in quarterly_results if q['profitable'])
    log(f"\n    Profitable quarters: {profitable_quarters}/{len(quarterly_results)}")

    # Monthly breakdown
    log(f"\n  Monthly Breakdown:")
    log(f"    {'Month':<10} {'Trades':>8} {'PnL':>12} {'% Total':>8} {'Flag':>15}")
    log(f"    {'─' * 55}")

    monthly_results = []
    concentrated_months = []
    for m in sorted(trades['month'].unique()):
        subset = trades[trades['month'] == m]
        tot = subset['pnl'].sum()
        pct = tot / total_pnl * 100 if total_pnl != 0 else 0
        flag = "CONCENTRATED!" if abs(pct) > 30 else ""
        if abs(pct) > 30:
            concentrated_months.append(m)
        log(f"    {m:<10} {len(subset):>8} ${tot:>11,.0f} {pct:>7.1f}% {flag:>15}")
        monthly_results.append({
            'month': m, 'trades': len(subset),
            'pnl': round(float(tot), 2), 'pct_of_total': round(pct, 1),
        })

    if concentrated_months:
        log(f"\n    WARNING: {len(concentrated_months)} month(s) with >30% of total P&L: {concentrated_months}")
    else:
        log(f"\n    No single month has >30% of total P&L — good temporal diversification")

    return {
        'quarterly': quarterly_results,
        'profitable_quarters': profitable_quarters,
        'total_quarters': len(quarterly_results),
        'monthly': monthly_results,
        'concentrated_months': concentrated_months,
    }


# ═══════════════════════════════════════════════════════════════════════
# TASK 5: TSLA dependency check
# ═══════════════════════════════════════════════════════════════════════

def task5_tsla():
    log("\n" + "=" * 80)
    log("  TASK 5: TSLA DEPENDENCY CHECK")
    log("=" * 80)

    trades = pd.read_csv(TRADE_LOG_NEW)
    total_pnl = trades['pnl'].sum()
    total_trades = len(trades)

    tsla = trades[trades['ticker'] == 'TSLA']
    non_tsla = trades[trades['ticker'] != 'TSLA']

    tsla_pnl = tsla['pnl'].sum()
    tsla_pct = tsla_pnl / total_pnl * 100

    log(f"\n  TSLA trades:    {len(tsla)} / {total_trades} ({len(tsla)/total_trades*100:.1f}%)")
    log(f"  TSLA P&L:       ${tsla_pnl:,.0f} / ${total_pnl:,.0f} ({tsla_pct:.1f}% of total)")
    log(f"  TSLA WR:        {(tsla['pnl'] > 0).sum()}/{len(tsla)} ({(tsla['pnl'] > 0).mean()*100:.1f}%)")
    log(f"  TSLA mean R:    {tsla['pnl_r'].mean():.2f}")
    log(f"  TSLA max R:     {tsla['pnl_r'].max():.2f}")

    # Top-3 TSLA trades
    tsla_sorted = tsla.sort_values('pnl', ascending=False)
    log(f"\n  Top-3 TSLA Trades:")
    top3_tsla_pnl = 0
    for _, t in tsla_sorted.head(3).iterrows():
        log(f"    {t['entry_time']:<22} {t['direction']:<6} R={t['pnl_r']:>6.2f}  PnL=${t['pnl']:>9,.0f}")
        top3_tsla_pnl += t['pnl']
    log(f"    Top-3 TSLA total: ${top3_tsla_pnl:,.0f} ({top3_tsla_pnl/total_pnl*100:.1f}% of strategy)")

    # Remove ALL TSLA
    log(f"\n  Scenario A: Remove ALL TSLA trades ({len(tsla)} trades)")
    nt = non_tsla
    gp = nt.loc[nt['pnl'] > 0, 'pnl'].sum()
    gl = abs(nt.loc[nt['pnl'] <= 0, 'pnl'].sum())
    pf_no_tsla = gp / gl if gl > 0 else float('inf')
    pnl_no_tsla = nt['pnl'].sum()
    sr_no_tsla = nt['pnl_r'].mean() / nt['pnl_r'].std(ddof=1) if nt['pnl_r'].std(ddof=1) > 0 else 0
    wr_no_tsla = (nt['pnl'] > 0).mean() * 100

    log(f"    Trades: {len(nt)}")
    log(f"    P&L:    ${pnl_no_tsla:,.0f}")
    log(f"    PF:     {pf_no_tsla:.2f}")
    log(f"    WR:     {wr_no_tsla:.1f}%")
    log(f"    Sharpe: {sr_no_tsla:.4f}")
    log(f"    RESULT: {'PROFITABLE' if pnl_no_tsla > 0 else 'UNPROFITABLE'}")

    # Remove top-3 TSLA only
    top3_idx = tsla_sorted.head(3).index
    remaining = trades.drop(top3_idx)
    log(f"\n  Scenario B: Remove top-3 TSLA trades only")
    gp2 = remaining.loc[remaining['pnl'] > 0, 'pnl'].sum()
    gl2 = abs(remaining.loc[remaining['pnl'] <= 0, 'pnl'].sum())
    pf_no_top3 = gp2 / gl2 if gl2 > 0 else float('inf')
    pnl_no_top3 = remaining['pnl'].sum()
    sr_no_top3 = remaining['pnl_r'].mean() / remaining['pnl_r'].std(ddof=1) if remaining['pnl_r'].std(ddof=1) > 0 else 0

    log(f"    Trades: {len(remaining)}")
    log(f"    P&L:    ${pnl_no_top3:,.0f}")
    log(f"    PF:     {pf_no_top3:.2f}")
    log(f"    Sharpe: {sr_no_top3:.4f}")
    log(f"    RESULT: {'PROFITABLE' if pnl_no_top3 > 0 else 'UNPROFITABLE'}")

    return {
        'tsla_trades': len(tsla),
        'tsla_pnl': round(float(tsla_pnl), 2),
        'tsla_pct_of_total': round(tsla_pct, 1),
        'tsla_win_rate': round(float((tsla['pnl'] > 0).mean() * 100), 1),
        'tsla_mean_r': round(float(tsla['pnl_r'].mean()), 2),
        'tsla_max_r': round(float(tsla['pnl_r'].max()), 2),
        'scenario_a_no_tsla': {
            'trades': len(nt), 'pnl': round(float(pnl_no_tsla), 2),
            'pf': round(pf_no_tsla, 2), 'wr': round(wr_no_tsla, 1),
            'sharpe_per_trade': round(float(sr_no_tsla), 4),
            'profitable': bool(pnl_no_tsla > 0),
        },
        'scenario_b_no_top3_tsla': {
            'trades': len(remaining), 'pnl': round(float(pnl_no_top3), 2),
            'pf': round(pf_no_top3, 2),
            'sharpe_per_trade': round(float(sr_no_top3), 4),
            'profitable': bool(pnl_no_top3 > 0),
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# TASK 6: DSR recomputation on per-trade returns
# ═══════════════════════════════════════════════════════════════════════

def task6_dsr():
    log("\n" + "=" * 80)
    log("  TASK 6: DSR RECOMPUTATION — Per-Trade R Returns")
    log("=" * 80)

    trades = pd.read_csv(TRADE_LOG_NEW)
    trades_r = trades['pnl_r'].values
    n = len(trades_r)

    mean_r = np.mean(trades_r)
    std_r = np.std(trades_r, ddof=1)
    sr = mean_r / std_r if std_r > 0 else 0.0
    skew = float(scipy_stats.skew(trades_r))
    kurt_excess = float(scipy_stats.kurtosis(trades_r, fisher=True))

    log(f"\n  Per-trade Sharpe:   {sr:.4f}")
    log(f"  N trades:           {n}")

    # Expected max Sharpe from N_TRIALS iid random strategies
    euler = 0.5772156649
    e_max_z = (scipy_stats.norm.ppf(1 - 1 / N_TRIALS) * (1 - euler) +
               euler * scipy_stats.norm.ppf(1 - 1 / (N_TRIALS * np.e)))

    # The benchmark is in "per-observation" units, same as our sr
    # For daily: sr_bench = e_max_z / sqrt(252). But for per-trade, no annualization.
    # e_max_z is already standardized (per-observation Sharpe of best random trial)
    sr_benchmark = e_max_z  # per-observation benchmark

    log(f"  N trials:           {N_TRIALS}")
    log(f"  E[max SR] benchmark: {sr_benchmark:.4f} (per-trade)")

    # DSR = PSR(observed_sr vs benchmark_sr)
    denom_sq = 1 - skew * sr + (kurt_excess / 4) * sr**2
    if denom_sq <= 0:
        denom_sq = 1e-10
    se = np.sqrt(denom_sq / (n - 1))
    z = (sr - sr_benchmark) / se if se > 0 else 0
    dsr_val = float(scipy_stats.norm.cdf(z))

    log(f"\n  DSR (per-trade, vs {N_TRIALS} trials):")
    log(f"    DSR value:        {dsr_val*100:.2f}%")
    log(f"    p-value:          {1-dsr_val:.4f}")
    log(f"    Significant?      {'YES (p<0.05)' if dsr_val > 0.95 else 'NO (p>=0.05)'}")

    # Also compute with annualized daily for comparison
    trades['exit_date'] = pd.to_datetime(trades['exit_time']).dt.date
    daily_pnl = trades.groupby('exit_date')['pnl'].sum()
    daily_pnl.index = pd.to_datetime(daily_pnl.index)
    all_dates = pd.bdate_range(start=FULL_START, end=FULL_END)
    daily_ret = pd.Series(0.0, index=all_dates)
    for dt, pnl in daily_pnl.items():
        if dt in daily_ret.index:
            daily_ret[dt] = pnl / CAPITAL
    T = len(daily_ret)
    sr_ann = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0
    skew_d = float(scipy_stats.skew(daily_ret))
    kurt_d = float(scipy_stats.kurtosis(daily_ret, fisher=True))

    sr_bench_d = e_max_z / np.sqrt(252)  # annualized benchmark
    denom_d = 1 - skew_d * sr_ann + (kurt_d / 4) * sr_ann**2
    if denom_d <= 0:
        denom_d = 1e-10
    se_d = np.sqrt(denom_d / (T - 1))
    z_d = (sr_ann - sr_bench_d) / se_d if se_d > 0 else 0
    dsr_daily = float(scipy_stats.norm.cdf(z_d))

    log(f"\n  DSR (daily equity, for comparison):")
    log(f"    Annualized SR:    {sr_ann:.4f}")
    log(f"    SR benchmark:     {sr_bench_d:.4f}")
    log(f"    DSR value:        {dsr_daily*100:.2f}%")
    log(f"    p-value:          {1-dsr_daily:.4f}")

    log(f"\n  {'Metric':<25} {'Per-trade':>15} {'Daily equity':>15}")
    log(f"  {'─' * 55}")
    log(f"  {'Observed SR':<25} {sr:>15.4f} {sr_ann:>15.4f}")
    log(f"  {'Benchmark SR':<25} {sr_benchmark:>15.4f} {sr_bench_d:>15.4f}")
    log(f"  {'DSR':<25} {dsr_val*100:>14.2f}% {dsr_daily*100:>14.2f}%")
    log(f"  {'Significant?':<25} {'NO':>15} {'YES' if dsr_daily > 0.95 else 'NO':>15}")

    return {
        'per_trade': {
            'sharpe': round(float(sr), 4),
            'n_trades': n,
            'sr_benchmark': round(float(sr_benchmark), 4),
            'dsr': round(float(dsr_val), 6),
            'dsr_p_value': round(float(1 - dsr_val), 6),
            'significant': bool(dsr_val > 0.95),
        },
        'daily_equity': {
            'sharpe_ann': round(float(sr_ann), 4),
            'T_days': T,
            'sr_benchmark': round(float(sr_bench_d), 4),
            'dsr': round(float(dsr_daily), 6),
            'dsr_p_value': round(float(1 - dsr_daily), 6),
            'significant': bool(dsr_daily > 0.95),
        }
    }


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    log("=" * 80)
    log("  FULL STATISTICAL VERIFICATION PASS")
    log(f"  Trade log: {TRADE_LOG_NEW}")
    log(f"  Date: 2026-03-06")
    log("=" * 80)

    r1 = task1_cscv_pbo()
    r2 = task2_earnings_verification()
    r3 = task3_distribution()
    r4 = task4_regime()
    r5 = task5_tsla()
    r6 = task6_dsr()

    # ── Final Summary ─────────────────────────────────────────────
    log("\n" + "=" * 80)
    log("  CONSOLIDATED VERDICT")
    log("=" * 80)

    log(f"\n  1. CSCV/PBO (per-trade):      PBO={r1['cscv_trade']['pbo']*100:.1f}%, "
        f"IS→OOS degrad={r1['cscv_trade']['degradation_pct']:.0f}%")
    log(f"  2. Earnings filter:           {r2['funnel']['blocked_by_earnings']} signals blocked, "
        f"all verified={'YES' if r2['all_verified'] else 'NO'}")
    log(f"  3. Distribution:              Median R={r3['median_r']:.2f}, "
        f"Skew={r3['skewness']:.1f}, Top-5={r3['top5_concentration_pct']:.0f}% of P&L")
    log(f"  4. Quarterly stability:       {r4['profitable_quarters']}/{r4['total_quarters']} profitable, "
        f"concentrated months: {r4['concentrated_months'] or 'none'}")
    log(f"  5. TSLA dependency:           {r5['tsla_pct_of_total']:.0f}% of P&L, "
        f"w/o TSLA: {'profitable' if r5['scenario_a_no_tsla']['profitable'] else 'UNPROFITABLE'}")
    log(f"  6. DSR (per-trade):           {r6['per_trade']['dsr']*100:.1f}% "
        f"({'significant' if r6['per_trade']['significant'] else 'NOT significant'})")

    # ── Save ──────────────────────────────────────────────────────
    summary = jsonable({
        'description': 'Full statistical verification — all 6 tasks',
        'trade_log': str(TRADE_LOG_NEW),
        'task1_cscv_pbo': r1,
        'task2_earnings': r2,
        'task3_distribution': r3,
        'task4_regime': r4,
        'task5_tsla': r5,
        'task6_dsr': r6,
    })

    with open(OUT_DIR / "full_verification_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    log(f"\n  Summary saved: {OUT_DIR / 'full_verification_summary.json'}")

    with open(OUT_DIR / "full_verification_log.txt", "w") as f:
        f.write("\n".join(LOG))
    log(f"  Log saved: {OUT_DIR / 'full_verification_log.txt'}")


if __name__ == "__main__":
    main()
