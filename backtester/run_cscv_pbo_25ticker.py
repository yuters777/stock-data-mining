"""
CSCV/PBO + DSR/MinTRL/PSR Analysis — 25-ticker Config A' dataset (202 trades)

Reuses the CSCV machinery from run_cscv_pbo.py but:
  - Runs all 16 strategy variants on the full 25-ticker universe
  - Computes DSR/MinTRL/PSR from Config A' daily equity curve
  - Generates logit_distribution.png and is_oos_scatter.png
  - Saves summary.json to results/phase3_cscv_pbo_25ticker/
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import json
import numpy as np
import pandas as pd
from itertools import combinations
from scipy import stats as scipy_stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from backtester.run_cscv_pbo import (
    define_strategies, build_config, run_strategy_get_daily_pnl,
    aggregate_m5_to_daily, compute_adx, compute_atr_series,
    sharpe_ratio, run_cscv_for_subset, CAPITAL,
)
from backtester.optimizer import load_ticker_data

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

TICKERS = [
    'AAPL', 'AMD', 'AMZN', 'AVGO', 'BA', 'BABA', 'BIDU', 'C', 'COIN', 'COST',
    'GOOGL', 'GS', 'IBIT', 'JPM', 'MARA', 'META', 'MSFT', 'MU', 'NVDA',
    'PLTR', 'SNOW', 'TSLA', 'TSM', 'TXN', 'V',
]

FULL_START = '2025-02-10'
FULL_END = '2026-01-31'

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'results', 'phase3_cscv_pbo_25ticker')
os.makedirs(RESULTS_DIR, exist_ok=True)

TRADE_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'results', 'phase3_25ticker_full', 'trades_a_prime.csv')

S = 16  # CSCV sub-blocks (task says 16 or closest power of 2)
N_TRIALS = 50  # for DSR

LOG = []


def log(msg=''):
    LOG.append(msg)
    print(msg)


# ═══════════════════════════════════════════════════════════════════════════
# DSR / MinTRL / PSR
# ═══════════════════════════════════════════════════════════════════════════

def compute_daily_equity_returns(trade_csv_path, capital=100_000.0):
    """Build daily equity returns from trade log."""
    trades = pd.read_csv(trade_csv_path)
    trades['exit_date'] = pd.to_datetime(trades['exit_time']).dt.date

    daily_pnl = trades.groupby('exit_date')['pnl'].sum()
    daily_pnl.index = pd.to_datetime(daily_pnl.index)
    daily_pnl = daily_pnl.sort_index()

    # Build full calendar of trading days
    all_dates = pd.bdate_range(start=FULL_START, end=FULL_END)
    daily_returns = pd.Series(0.0, index=all_dates)
    for dt, pnl in daily_pnl.items():
        if dt in daily_returns.index:
            daily_returns[dt] = pnl / capital

    return daily_returns


def annualized_sharpe(daily_returns):
    """Annualized Sharpe from daily returns."""
    if len(daily_returns) < 2 or daily_returns.std() == 0:
        return 0.0
    return daily_returns.mean() / daily_returns.std() * np.sqrt(252)


def psr(observed_sharpe, T, sr_benchmark=0.0, skew=0.0, kurtosis=3.0):
    """Probabilistic Sharpe Ratio (Bailey & López de Prado)."""
    se = np.sqrt((1 - skew * observed_sharpe + (kurtosis - 1) / 4 * observed_sharpe**2) / T)
    if se == 0:
        return 0.5
    z = (observed_sharpe - sr_benchmark) / se
    return float(scipy_stats.norm.cdf(z))


def deflated_sharpe_ratio(observed_sharpe, T, N_trials, daily_returns):
    """DSR — deflates Sharpe by expected max from N random trials."""
    skew = float(scipy_stats.skew(daily_returns))
    kurt = float(scipy_stats.kurtosis(daily_returns, fisher=False))  # excess=False -> raw kurtosis

    # Expected maximum Sharpe from N iid trials (Bailey & López de Prado 2014)
    euler_mascheroni = 0.5772156649
    e_max_z = scipy_stats.norm.ppf(1 - 1 / N_trials) * (1 - euler_mascheroni) + \
              euler_mascheroni * scipy_stats.norm.ppf(1 - 1 / (N_trials * np.e))

    # Convert to annualized Sharpe scale
    sr_benchmark = e_max_z / np.sqrt(252)  # daily -> annualized benchmark

    se = np.sqrt((1 - skew * observed_sharpe + (kurt - 1) / 4 * observed_sharpe**2) / T)
    if se == 0:
        return 0.5, sr_benchmark

    z = (observed_sharpe - sr_benchmark) / se
    return float(scipy_stats.norm.cdf(z)), float(sr_benchmark)


def min_track_record_length(observed_sharpe, sr_benchmark=0.0, skew=0.0, kurtosis=3.0,
                             confidence=0.95):
    """MinTRL — minimum T needed for Sharpe to be significant at given confidence."""
    z_alpha = scipy_stats.norm.ppf(confidence)
    sr_diff = observed_sharpe - sr_benchmark
    if sr_diff <= 0:
        return float('inf')

    numerator = 1 - skew * observed_sharpe + (kurtosis - 1) / 4 * observed_sharpe**2
    return numerator * (z_alpha / sr_diff) ** 2


def run_dsr_mintrl(trade_csv_path):
    """Run DSR/MinTRL/PSR diagnostics and return results dict."""
    log("\n" + "=" * 80)
    log("  DSR / MinTRL / PSR DIAGNOSTICS")
    log("=" * 80)

    daily_ret = compute_daily_equity_returns(trade_csv_path)
    T = len(daily_ret)
    n_nonzero = (daily_ret != 0).sum()

    sr_ann = annualized_sharpe(daily_ret)
    skew = float(scipy_stats.skew(daily_ret))
    kurt = float(scipy_stats.kurtosis(daily_ret, fisher=False))

    log(f"  Daily equity returns: T={T} days ({n_nonzero} with trades)")
    log(f"  Raw Sharpe (annualized): {sr_ann:.4f}")
    log(f"  Skewness: {skew:.4f}")
    log(f"  Kurtosis (raw): {kurt:.4f}")

    # PSR vs zero benchmark
    psr_val = psr(sr_ann, T, sr_benchmark=0.0, skew=skew, kurtosis=kurt)
    log(f"\n  PSR (vs SR=0 benchmark): {psr_val*100:.1f}% (p={1-psr_val:.4f})")

    # DSR vs N_TRIALS
    dsr_val, sr_bench = deflated_sharpe_ratio(sr_ann, T, N_TRIALS, daily_ret)
    log(f"  DSR (vs {N_TRIALS} trials): {dsr_val*100:.1f}% (benchmark SR={sr_bench:.4f})")

    # MinTRL
    mintrl = min_track_record_length(sr_ann, sr_benchmark=0.0, skew=skew, kurtosis=kurt)
    have_enough = T >= mintrl
    log(f"\n  MinTRL (95% conf vs SR=0): {mintrl:.0f} days")
    log(f"  Actual track record: {T} days")
    log(f"  MinTRL reached? {'YES' if have_enough else 'NO'} "
        f"({'sufficient' if have_enough else f'need {mintrl-T:.0f} more days'})")

    # Also compute MinTRL in trade-count terms
    trades = pd.read_csv(trade_csv_path)
    n_trades = len(trades)
    trades_per_day = n_trades / n_nonzero if n_nonzero > 0 else 0
    log(f"  Trades: {n_trades} ({trades_per_day:.2f}/trading day)")

    return {
        'T_days': int(T),
        'n_trade_days': int(n_nonzero),
        'n_trades': int(n_trades),
        'sharpe_annualized': float(sr_ann),
        'skewness': float(skew),
        'kurtosis_raw': float(kurt),
        'psr_vs_zero': float(psr_val),
        'psr_p_value': float(1 - psr_val),
        'dsr_vs_50trials': float(dsr_val),
        'dsr_benchmark_sr': float(sr_bench),
        'mintrl_days': float(mintrl),
        'mintrl_reached': bool(have_enough),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CSCV / PBO (reused from run_cscv_pbo.py, adapted for 25 tickers & S=16)
# ═══════════════════════════════════════════════════════════════════════════

def run_cscv_analysis():
    """Run full CSCV/PBO on 16 strategies × 25 tickers."""
    log("\n" + "=" * 80)
    log("  CSCV / PBO ANALYSIS — 25-ticker universe")
    log("  Bailey, Borwein, López de Prado, Zhu (2015)")
    log("=" * 80)
    log(f"  Tickers: {len(TICKERS)}  |  Period: {FULL_START} -> {FULL_END}")
    log(f"  CSCV blocks: S={S}  |  Splits: C({S},{S//2})")
    log("")

    # Step 1: Load daily data for regime post-filters
    log("  Step 1: Loading data and computing daily indicators...")
    daily_data = {}
    for ticker in TICKERS:
        m5_df = load_ticker_data(ticker)
        daily = aggregate_m5_to_daily(m5_df)
        daily['ADX'] = compute_adx(daily, period=14)
        daily['ATR5'] = compute_atr_series(daily, period=5)
        daily['ATR20'] = compute_atr_series(daily, period=20)
        daily['ATR_ratio_5_20'] = daily['ATR5'] / daily['ATR20'].replace(0, np.nan)
        daily['ATR_ratio_5_20'] = daily['ATR_ratio_5_20'].fillna(1.0)
        daily_data[ticker] = daily
        log(f"    {ticker}: {len(daily)} days")

    # Step 2: Run 16 strategies
    strategies = define_strategies()
    N = len(strategies)
    log(f"\n  Step 2: Running {N} strategy variants on {len(TICKERS)} tickers...")

    all_daily_pnls = []
    strategy_names = []

    for si, strat in enumerate(strategies):
        strat_start = time.time()
        config = build_config(strat['name'], strat['params'])

        daily_pnl = run_strategy_get_daily_pnl(
            config, TICKERS, FULL_START, FULL_END, daily_data,
            adx_thresh=strat.get('adx_thresh'),
            atr_ratio_thresh=strat.get('atr_ratio_thresh'),
        )

        total_pnl = sum(daily_pnl.values())
        n_trade_days = sum(1 for v in daily_pnl.values() if v != 0)
        elapsed = time.time() - strat_start

        log(f"    [{si:>2}] {strat['name']:<30} "
            f"P&L=${total_pnl:>8,.0f}  trade_days={n_trade_days:>3}  [{elapsed:.1f}s]")

        all_daily_pnls.append(daily_pnl)
        strategy_names.append(strat['name'])

    # Step 3: Build trials matrix M (T × N)
    log(f"\n  Step 3: Building trials matrix...")
    all_dates = set()
    for dp in all_daily_pnls:
        all_dates.update(dp.keys())
    all_dates = sorted(all_dates)
    T = len(all_dates)
    log(f"    Total trading days: {T}")

    M = np.zeros((T, N))
    for j, dp in enumerate(all_daily_pnls):
        for i, date_str in enumerate(all_dates):
            M[i, j] = dp.get(date_str, 0.0) / CAPITAL

    # Per-strategy summary
    log(f"\n    {'#':>4} {'Strategy':<30} {'SR':>8} {'Total%':>8}")
    log(f"    {'─' * 54}")
    for j in range(N):
        sr = sharpe_ratio(M[:, j])
        log(f"    {j:>4} {strategy_names[j]:<30} {sr:>7.3f} {np.sum(M[:, j])*100:>7.3f}%")

    # Step 4: Run CSCV
    log(f"\n  Step 4: Running CSCV (S={S})...")
    focus_idx = 0  # S00_ConfigA_Simplified
    cscv = run_cscv_for_subset(M, strategy_names, focus_idx, S=S)

    return cscv, M, strategy_names, T


def report_cscv(cscv, M, strategy_names, T):
    """Report CSCV results and return metrics dict."""
    pbo = cscv['pbo']
    logits = cscv['logits']
    is_sr = cscv['is_sharpes']
    oos_sr = cscv['oos_sharpes']
    N = M.shape[1]

    log(f"\n{'=' * 80}")
    log(f"  CSCV / PBO RESULTS")
    log(f"{'=' * 80}")

    # PBO
    log(f"\n  PBO = {pbo:.4f} ({pbo*100:.1f}%)")
    log(f"  OOS-negative splits: {cscv['oos_negative_count']} / {cscv['n_splits']}")

    # Logit distribution
    log(f"\n  Logit distribution:")
    log(f"    Mean:   {np.mean(logits):.4f}")
    log(f"    Median: {np.median(logits):.4f}")
    log(f"    Std:    {np.std(logits):.4f}")

    # IS→OOS degradation
    degradation = np.mean(is_sr) - np.mean(oos_sr)
    degradation_pct = degradation / abs(np.mean(is_sr)) * 100 if np.mean(is_sr) != 0 else 0.0

    log(f"\n  IS→OOS degradation:")
    log(f"    IS Sharpe mean:  {np.mean(is_sr):.4f}")
    log(f"    OOS Sharpe mean: {np.mean(oos_sr):.4f}")
    log(f"    Degradation: {degradation_pct:.1f}%")

    # IS-OOS correlation
    corr, p_val = scipy_stats.pearsonr(is_sr, oos_sr) if len(is_sr) > 2 else (0.0, 1.0)
    log(f"\n  IS-OOS correlation: r={corr:.4f} (p={p_val:.4f})")

    # Focus strategy
    log(f"\n  Config A focus:")
    log(f"    Selected as IS-best: {cscv['focus_selected_count']}/{cscv['n_splits']} "
        f"({cscv['focus_selected_pct']:.1f}%)")
    config_a_sr = sharpe_ratio(M[:, 0])
    log(f"    Full-sample SR: {config_a_sr:.4f}")

    if len(cscv['focus_oos_sharpes']) > 0:
        log(f"    OOS Sharpe when selected: mean={np.mean(cscv['focus_oos_sharpes']):.4f}")
    else:
        log(f"    Config A was NEVER selected as IS-best")

    # Most frequently IS-best
    from collections import Counter
    best_counts = Counter(cscv['is_best_indices'])
    log(f"\n  Most frequent IS-best strategies:")
    for idx, count in best_counts.most_common(5):
        log(f"    {strategy_names[idx]}: {count}/{cscv['n_splits']} "
            f"({count/cscv['n_splits']*100:.1f}%)")

    return {
        'pbo': float(pbo),
        'n_splits': int(cscv['n_splits']),
        'oos_negative_count': int(cscv['oos_negative_count']),
        'logit_mean': float(np.mean(logits)),
        'logit_median': float(np.median(logits)),
        'logit_std': float(np.std(logits)),
        'is_sharpe_mean': float(np.mean(is_sr)),
        'oos_sharpe_mean': float(np.mean(oos_sr)),
        'degradation_pct': float(degradation_pct),
        'is_oos_correlation_r': float(corr),
        'is_oos_correlation_p': float(p_val),
        'S': S,
        'T_days': int(T),
        'T_used': int(cscv['T_used']),
        'block_size': int(cscv['block_size']),
        'N_strategies': int(M.shape[1]),
        'focus_strategy': cscv['focus_strategy'],
        'focus_selected_pct': float(cscv['focus_selected_pct']),
        'config_a_full_sr': float(config_a_sr),
    }


# ═══════════════════════════════════════════════════════════════════════════
# PLOTS
# ═══════════════════════════════════════════════════════════════════════════

def plot_logit_distribution(logits, pbo, save_path):
    """Logit distribution histogram."""
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(logits, bins=30, color='steelblue', edgecolor='white', alpha=0.8)
    ax.axvline(x=0, color='red', linestyle='--', linewidth=1.5, label='logit=0 (random)')
    ax.axvline(x=np.mean(logits), color='orange', linestyle='-', linewidth=1.5,
               label=f'mean={np.mean(logits):.2f}')
    ax.set_xlabel('Logit (λ)')
    ax.set_ylabel('Count')
    ax.set_title(f'CSCV Logit Distribution — PBO={pbo:.1%}\n'
                 f'25 tickers, S={S}, {len(logits)} splits')
    ax.legend()
    plt.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    log(f"  Saved: {save_path}")


def plot_is_oos_scatter(is_sr, oos_sr, corr, save_path):
    """IS vs OOS Sharpe scatter plot."""
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(is_sr, oos_sr, alpha=0.3, s=10, color='steelblue')

    # Regression line
    if len(is_sr) > 2:
        z = np.polyfit(is_sr, oos_sr, 1)
        p = np.poly1d(z)
        x_range = np.linspace(is_sr.min(), is_sr.max(), 100)
        ax.plot(x_range, p(x_range), 'r-', linewidth=1.5, label=f'r={corr:.3f}')

    ax.axhline(y=0, color='gray', linestyle=':', alpha=0.5)
    ax.axvline(x=0, color='gray', linestyle=':', alpha=0.5)
    ax.set_xlabel('IS Sharpe (best strategy)')
    ax.set_ylabel('OOS Sharpe (IS-best strategy)')
    ax.set_title(f'IS vs OOS Sharpe — CSCV\nr={corr:.3f}, 25 tickers, S={S}')
    ax.legend()
    plt.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    log(f"  Saved: {save_path}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    # ── Part 1: DSR / MinTRL / PSR ────────────────────────────────────
    dsr_results = run_dsr_mintrl(TRADE_LOG)

    # ── Part 2: CSCV / PBO ───────────────────────────────────────────
    cscv, M, strategy_names, T = run_cscv_analysis()
    cscv_results = report_cscv(cscv, M, strategy_names, T)

    # ── Part 3: Comparison table ──────────────────────────────────────
    log(f"\n{'=' * 80}")
    log(f"  COMPARISON: 54 trades (prev) vs 202 trades (new)")
    log(f"{'=' * 80}")
    log(f"  {'Metric':<25} {'54 trades (prev)':>20} {'202 trades (new)':>20}")
    log(f"  {'─' * 65}")
    log(f"  {'PBO':<25} {'18.6%':>20} {cscv_results['pbo']*100:>19.1f}%")
    log(f"  {'Logit mean':<25} {'-0.51':>20} {cscv_results['logit_mean']:>20.4f}")
    log(f"  {'IS→OOS degrad':<25} {'60.6%':>20} {cscv_results['degradation_pct']:>19.1f}%")
    log(f"  {'IS-OOS corr':<25} {'-0.42':>20} {cscv_results['is_oos_correlation_r']:>20.4f}")
    log(f"  {'PSR':<25} {'78.6% (p=0.21)':>20} {dsr_results['psr_vs_zero']*100:>14.1f}% (p={dsr_results['psr_p_value']:.2f})")
    log(f"  {'MinTRL reached?':<25} {'No (54<202)':>20} {'Yes' if dsr_results['mintrl_reached'] else 'No':>20}")
    log(f"  {'Sharpe (ann.)':<25} {'':>20} {dsr_results['sharpe_annualized']:>20.4f}")
    log(f"  {'DSR (50 trials)':<25} {'':>20} {dsr_results['dsr_vs_50trials']*100:>19.1f}%")

    # ── Part 4: Plots ────────────────────────────────────────────────
    log(f"\n  Generating plots...")
    plot_logit_distribution(
        cscv['logits'], cscv['pbo'],
        os.path.join(RESULTS_DIR, 'logit_distribution.png'))
    plot_is_oos_scatter(
        cscv['is_sharpes'], cscv['oos_sharpes'],
        cscv_results['is_oos_correlation_r'],
        os.path.join(RESULTS_DIR, 'is_oos_scatter.png'))

    # ── Save ─────────────────────────────────────────────────────────
    elapsed = time.time() - t0

    summary = {
        'description': 'CSCV/PBO + DSR/MinTRL/PSR — 25-ticker Config A\' (202 trades)',
        'period': f'{FULL_START} to {FULL_END}',
        'tickers': TICKERS,
        'n_tickers': len(TICKERS),
        'dsr_mintrl': dsr_results,
        'cscv_pbo': cscv_results,
        'comparison_with_previous': {
            'prev_pbo': 0.186,
            'prev_logit_mean': -0.51,
            'prev_degradation_pct': 60.6,
            'prev_is_oos_corr': -0.42,
            'prev_psr': 0.786,
            'new_pbo': cscv_results['pbo'],
            'new_logit_mean': cscv_results['logit_mean'],
            'new_degradation_pct': cscv_results['degradation_pct'],
            'new_is_oos_corr': cscv_results['is_oos_correlation_r'],
            'new_psr': dsr_results['psr_vs_zero'],
        },
        'elapsed_seconds': elapsed,
    }

    json_path = os.path.join(RESULTS_DIR, 'summary.json')
    with open(json_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    log(f"\n  Summary saved: {json_path}")

    # Save full log
    log_path = os.path.join(RESULTS_DIR, 'analysis_log.txt')
    with open(log_path, 'w') as f:
        f.write('\n'.join(LOG))

    log(f"\n  Completed in {elapsed:.0f}s ({elapsed/60:.1f}min)")


if __name__ == '__main__':
    main()
