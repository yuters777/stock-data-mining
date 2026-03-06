"""
PSR/MinTRL Verification: Daily equity returns vs Per-trade R returns.

Addresses the concern that computing Sharpe on daily equity (with many
zero-return days) inflates the ratio for a low-frequency strategy.

Tasks:
  1. Audit old daily-equity approach (reproduce old numbers)
  2. Recompute PSR/MinTRL from per-trade R-multiples
  3. Side-by-side comparison
  4. Stationary block bootstrap on trade-level returns
  5. Save results to results/phase3_psr_verification/
"""

import json
import os
import sys
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Config ─────────────────────────────────────────────────────────────
TRADE_LOG = Path(__file__).resolve().parent.parent / \
    "results" / "phase3_25ticker_earnings_fix" / "trades_a_prime.csv"
RESULTS_DIR = Path(__file__).resolve().parent.parent / \
    "results" / "phase3_psr_verification"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

FULL_START = "2025-02-10"
FULL_END = "2026-01-31"
CAPITAL = 100_000.0
N_TRIALS = 50
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_BLOCK_SIZE = 5

LOG_LINES = []

def log(msg=""):
    print(msg)
    LOG_LINES.append(msg)


# ── PSR / MinTRL formulas ──────────────────────────────────────────────

def psr_formula(sr, n, skew, kurt_excess, sr_benchmark=0.0):
    """PSR per Bailey & López de Prado (2012).

    Args:
        sr: observed Sharpe ratio
        n: number of observations (days or trades)
        skew: skewness of returns
        kurt_excess: EXCESS kurtosis (kurtosis - 3)
        sr_benchmark: benchmark Sharpe to test against
    """
    denom_sq = 1 - skew * sr + (kurt_excess / 4) * sr**2
    if denom_sq <= 0:
        denom_sq = 1e-10
    se = np.sqrt(denom_sq / (n - 1))
    if se == 0:
        return 0.5
    z = (sr - sr_benchmark) / se
    return float(scipy_stats.norm.cdf(z))


def mintrl_formula(sr, skew, kurt_excess, sr_benchmark=0.0, confidence=0.95):
    """MinTRL per Bailey & López de Prado.

    Returns minimum number of observations needed for SR to be significant.
    """
    z_alpha = scipy_stats.norm.ppf(confidence)
    sr_diff = sr - sr_benchmark
    if sr_diff <= 0:
        return float('inf')
    numer = 1 - skew * sr + (kurt_excess / 4) * sr**2
    return 1 + numer * (z_alpha / sr_diff) ** 2


# ── Task 1: Reproduce old daily-equity approach ───────────────────────

def task1_daily_equity():
    log("=" * 80)
    log("  TASK 1: AUDIT — Daily Equity Returns (old approach)")
    log("=" * 80)

    trades = pd.read_csv(TRADE_LOG)
    trades['exit_date'] = pd.to_datetime(trades['exit_time']).dt.date
    daily_pnl = trades.groupby('exit_date')['pnl'].sum()
    daily_pnl.index = pd.to_datetime(daily_pnl.index)

    all_dates = pd.bdate_range(start=FULL_START, end=FULL_END)
    daily_ret = pd.Series(0.0, index=all_dates)
    for dt, pnl in daily_pnl.items():
        if dt in daily_ret.index:
            daily_ret[dt] = pnl / CAPITAL

    T = len(daily_ret)
    n_nonzero = int((daily_ret != 0).sum())
    n_zero = T - n_nonzero

    sr_ann = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0.0
    skew = float(scipy_stats.skew(daily_ret))
    # Old code used fisher=False (raw kurtosis), but PSR formula expects excess
    kurt_raw = float(scipy_stats.kurtosis(daily_ret, fisher=False))
    kurt_excess = kurt_raw - 3.0  # convert to excess

    log(f"\n  N (business days):      {T}")
    log(f"  Days with trades:       {n_nonzero}")
    log(f"  Days with ZERO return:  {n_zero} ({n_zero/T*100:.1f}%)")
    log(f"  Daily mean return:      {daily_ret.mean():.6f}")
    log(f"  Daily std return:       {daily_ret.std():.6f}")
    log(f"  Sharpe (annualized):    {sr_ann:.4f}")
    log(f"  Skewness:               {skew:.4f}")
    log(f"  Kurtosis (raw):         {kurt_raw:.4f}")
    log(f"  Kurtosis (excess):      {kurt_excess:.4f}")

    # NOTE: The old code passed raw kurtosis to PSR where (kurtosis-1)/4 was used.
    # This is actually using (raw_kurt - 1)/4, which is different from the
    # standard formula that uses excess_kurtosis/4. Let me reproduce both.

    # Old code's PSR (using its formula with raw kurtosis and (kurtosis-1)/4):
    se_old = np.sqrt((1 - skew * sr_ann + (kurt_raw - 1) / 4 * sr_ann**2) / T)
    psr_old = float(scipy_stats.norm.cdf(sr_ann / se_old)) if se_old > 0 else 0.5

    # Correct PSR (using excess kurtosis):
    psr_correct = psr_formula(sr_ann, T, skew, kurt_excess, sr_benchmark=0.0)

    # Old MinTRL (using raw kurtosis and (kurtosis-1)/4):
    z95 = scipy_stats.norm.ppf(0.95)
    mintrl_old = (1 - skew * sr_ann + (kurt_raw - 1) / 4 * sr_ann**2) * (z95 / sr_ann) ** 2

    # Correct MinTRL:
    mintrl_correct = mintrl_formula(sr_ann, skew, kurt_excess, sr_benchmark=0.0)

    log(f"\n  PSR (old code, raw kurt):     {psr_old*100:.2f}%")
    log(f"  PSR (corrected, excess kurt): {psr_correct*100:.2f}%")
    log(f"  MinTRL (old code):            {mintrl_old:.1f} days")
    log(f"  MinTRL (corrected):           {mintrl_correct:.1f} days")

    log(f"\n  PROBLEM: {n_zero} zero-return days ({n_zero/T*100:.0f}% of series)")
    log(f"  inflate T but not information content → PSR is overstated")

    return {
        'T_days': T,
        'n_trade_days': n_nonzero,
        'n_zero_days': n_zero,
        'zero_pct': round(n_zero / T * 100, 1),
        'mean_daily': float(daily_ret.mean()),
        'std_daily': float(daily_ret.std()),
        'sharpe_annualized': round(sr_ann, 4),
        'skewness': round(skew, 4),
        'kurtosis_raw': round(kurt_raw, 4),
        'kurtosis_excess': round(kurt_excess, 4),
        'psr_old_formula': round(psr_old, 6),
        'psr_corrected': round(psr_correct, 6),
        'mintrl_old': round(mintrl_old, 1),
        'mintrl_corrected': round(mintrl_correct, 1),
        'mintrl_reached': T >= mintrl_correct,
    }


# ── Task 2: Per-trade R returns ───────────────────────────────────────

def task2_per_trade_r():
    log("\n" + "=" * 80)
    log("  TASK 2: RECOMPUTE — Per-Trade R-Multiple Returns")
    log("=" * 80)

    trades = pd.read_csv(TRADE_LOG)
    trades_r = trades['pnl_r'].values
    n = len(trades_r)

    mean_r = np.mean(trades_r)
    std_r = np.std(trades_r, ddof=1)
    sr_trades = mean_r / std_r if std_r > 0 else 0.0  # NOT annualized

    skew = float(scipy_stats.skew(trades_r))
    kurt_excess = float(scipy_stats.kurtosis(trades_r, fisher=True))  # fisher=True = excess
    kurt_raw = kurt_excess + 3.0

    log(f"\n  N trades:               {n}")
    log(f"  Mean R:                 {mean_r:.4f}")
    log(f"  Std R:                  {std_r:.4f}")
    log(f"  Sharpe (per-trade):     {sr_trades:.4f}")
    log(f"  Skewness:               {skew:.4f}")
    log(f"  Kurtosis (excess):      {kurt_excess:.4f}")
    log(f"  Kurtosis (raw):         {kurt_raw:.4f}")

    # PSR vs zero benchmark
    psr_val = psr_formula(sr_trades, n, skew, kurt_excess, sr_benchmark=0.0)
    log(f"\n  PSR vs SR=0:            {psr_val*100:.2f}% (p={1-psr_val:.4f})")

    # MinTRL
    mintrl = mintrl_formula(sr_trades, skew, kurt_excess, sr_benchmark=0.0)
    have_enough = n >= mintrl
    log(f"  MinTRL (trades):        {mintrl:.0f}")
    log(f"  Have:                   {n} trades")
    log(f"  MinTRL reached?         {'YES' if have_enough else 'NO'}")

    if not have_enough:
        log(f"  Need {mintrl - n:.0f} more trades")

    # Distribution details
    winners = trades_r[trades_r > 0]
    losers = trades_r[trades_r <= 0]
    log(f"\n  Winners: {len(winners)} (mean R = {winners.mean():.2f})")
    log(f"  Losers:  {len(losers)} (mean R = {losers.mean():.2f})")
    log(f"  Win rate: {len(winners)/n*100:.1f}%")
    log(f"  Max R: {trades_r.max():.2f}, Min R: {trades_r.min():.2f}")

    return {
        'n_trades': n,
        'mean_r': round(float(mean_r), 4),
        'std_r': round(float(std_r), 4),
        'sharpe_per_trade': round(float(sr_trades), 4),
        'skewness': round(skew, 4),
        'kurtosis_excess': round(kurt_excess, 4),
        'kurtosis_raw': round(kurt_raw, 4),
        'psr_vs_zero': round(float(psr_val), 6),
        'psr_p_value': round(float(1 - psr_val), 6),
        'mintrl_trades': round(float(mintrl), 1) if mintrl != float('inf') else "inf",
        'mintrl_reached': bool(have_enough),
        'win_rate': round(len(winners) / n * 100, 1),
        'max_r': round(float(trades_r.max()), 2),
        'min_r': round(float(trades_r.min()), 2),
    }


# ── Task 3: Side-by-side comparison ──────────────────────────────────

def task3_comparison(daily_results, trade_results):
    log("\n" + "=" * 80)
    log("  TASK 3: SIDE-BY-SIDE COMPARISON")
    log("=" * 80)

    log(f"\n  {'Metric':<25} {'Daily equity (old)':>20} {'Per-trade R (new)':>20}")
    log(f"  {'─' * 65}")
    log(f"  {'N':<25} {daily_results['T_days']:>17} days {trade_results['n_trades']:>16} trades")
    log(f"  {'Zero-information obs':<25} {daily_results['n_zero_days']:>17} days {'0':>16} trades")
    log(f"  {'Sharpe':<25} {daily_results['sharpe_annualized']:>20.4f} {trade_results['sharpe_per_trade']:>20.4f}")
    log(f"  {'Skewness':<25} {daily_results['skewness']:>20.4f} {trade_results['skewness']:>20.4f}")
    log(f"  {'Kurtosis (excess)':<25} {daily_results['kurtosis_excess']:>20.4f} {trade_results['kurtosis_excess']:>20.4f}")
    log(f"  {'PSR vs zero':<25} {daily_results['psr_corrected']*100:>19.2f}% {trade_results['psr_vs_zero']*100:>19.2f}%")

    mintrl_daily = daily_results['mintrl_corrected']
    mintrl_trade = trade_results['mintrl_trades']
    mintrl_trade_str = f"{mintrl_trade}" if mintrl_trade != "inf" else "∞"

    log(f"  {'MinTRL':<25} {mintrl_daily:>17.0f} days {mintrl_trade_str:>16} trades")
    log(f"  {'MinTRL reached?':<25} {'YES' if daily_results['mintrl_reached'] else 'NO':>20} {'YES' if trade_results['mintrl_reached'] else 'NO':>20}")

    log(f"\n  KEY FINDING:")
    if trade_results['psr_vs_zero'] < daily_results['psr_corrected']:
        log(f"  Per-trade PSR ({trade_results['psr_vs_zero']*100:.1f}%) is LOWER than "
            f"daily-equity PSR ({daily_results['psr_corrected']*100:.1f}%)")
        log(f"  The {daily_results['n_zero_days']} zero-return days were inflating the daily PSR")
    else:
        log(f"  Per-trade PSR ({trade_results['psr_vs_zero']*100:.1f}%) is comparable to "
            f"daily-equity PSR ({daily_results['psr_corrected']*100:.1f}%)")

    if not trade_results['mintrl_reached']:
        log(f"  CRITICAL: MinTRL NOT reached on per-trade basis!")
        log(f"  Need {mintrl_trade} trades, only have {trade_results['n_trades']}")

    return {
        'daily_psr': daily_results['psr_corrected'],
        'trade_psr': trade_results['psr_vs_zero'],
        'daily_mintrl': mintrl_daily,
        'trade_mintrl': mintrl_trade,
        'daily_mintrl_reached': daily_results['mintrl_reached'],
        'trade_mintrl_reached': trade_results['mintrl_reached'],
        'zero_days_inflating': daily_results['n_zero_days'],
    }


# ── Task 4: Block bootstrap ──────────────────────────────────────────

def task4_block_bootstrap():
    log("\n" + "=" * 80)
    log("  TASK 4: STATIONARY BLOCK BOOTSTRAP (trade-level)")
    log("=" * 80)

    trades = pd.read_csv(TRADE_LOG)
    trades_r = trades['pnl_r'].values
    n = len(trades_r)
    block_size = BOOTSTRAP_BLOCK_SIZE
    n_resamples = BOOTSTRAP_RESAMPLES

    log(f"\n  N trades:         {n}")
    log(f"  Block size:       {block_size}")
    log(f"  Resamples:        {n_resamples:,}")

    rng = np.random.default_rng(42)
    bootstrap_sharpes = np.empty(n_resamples)

    for i in range(n_resamples):
        # Stationary block bootstrap: random start points, wrap around
        sample = np.empty(n)
        pos = 0
        while pos < n:
            # Random start point
            start = rng.integers(0, n)
            # Geometric block length (mean = block_size)
            blen = rng.geometric(1.0 / block_size)
            blen = min(blen, n - pos)  # don't exceed needed length

            for j in range(blen):
                sample[pos] = trades_r[(start + j) % n]
                pos += 1
                if pos >= n:
                    break

        mean_s = np.mean(sample)
        std_s = np.std(sample, ddof=1)
        bootstrap_sharpes[i] = mean_s / std_s if std_s > 0 else 0.0

    # Original Sharpe
    orig_sr = np.mean(trades_r) / np.std(trades_r, ddof=1)

    # Results
    ci_lower = np.percentile(bootstrap_sharpes, 2.5)
    ci_upper = np.percentile(bootstrap_sharpes, 97.5)
    pct_positive = (bootstrap_sharpes > 0).mean() * 100
    median_sr = np.median(bootstrap_sharpes)

    log(f"\n  Original Sharpe (per-trade):  {orig_sr:.4f}")
    log(f"  Bootstrap median:             {median_sr:.4f}")
    log(f"  Bootstrap mean:               {bootstrap_sharpes.mean():.4f}")
    log(f"  Bootstrap std:                {bootstrap_sharpes.std():.4f}")
    log(f"  95% CI:                       [{ci_lower:.4f}, {ci_upper:.4f}]")
    log(f"  % resamples with SR > 0:      {pct_positive:.1f}%")

    # Does CI include zero?
    ci_includes_zero = ci_lower <= 0 <= ci_upper
    log(f"  95% CI includes zero?         {'YES — not significant' if ci_includes_zero else 'NO — significant at 5%'}")

    # Also compute bootstrap PSR (proportion > 0)
    log(f"\n  Bootstrap PSR (empirical):    {pct_positive:.1f}%")
    log(f"  (vs analytical PSR above)")

    return {
        'n_trades': n,
        'block_size': block_size,
        'n_resamples': n_resamples,
        'original_sharpe': round(float(orig_sr), 4),
        'bootstrap_median': round(float(median_sr), 4),
        'bootstrap_mean': round(float(bootstrap_sharpes.mean()), 4),
        'bootstrap_std': round(float(bootstrap_sharpes.std()), 4),
        'ci_95_lower': round(float(ci_lower), 4),
        'ci_95_upper': round(float(ci_upper), 4),
        'pct_positive': round(float(pct_positive), 1),
        'ci_includes_zero': bool(ci_includes_zero),
        'significant_at_5pct': not ci_includes_zero,
    }


# ── Main ──────────────────────────────────────────────────────────────

def main():
    log("=" * 80)
    log("  PSR / MinTRL VERIFICATION: Daily vs Per-Trade Returns")
    log(f"  Trade log: {TRADE_LOG}")
    log("=" * 80)

    daily_results = task1_daily_equity()
    trade_results = task2_per_trade_r()
    comparison = task3_comparison(daily_results, trade_results)
    bootstrap_results = task4_block_bootstrap()

    # ── Summary ────────────────────────────────────────────────────────
    log("\n" + "=" * 80)
    log("  FINAL VERDICT")
    log("=" * 80)

    log(f"\n  ChatGPT PRO was {'CORRECT' if trade_results['psr_vs_zero'] < daily_results['psr_corrected'] else 'WRONG'}:")
    log(f"  Daily-equity PSR ({daily_results['psr_corrected']*100:.1f}%) {'>' if daily_results['psr_corrected'] > trade_results['psr_vs_zero'] else '<='} "
        f"Per-trade PSR ({trade_results['psr_vs_zero']*100:.1f}%)")

    mintrl_t = trade_results['mintrl_trades']
    if mintrl_t == "inf":
        log(f"  MinTRL is infinite (negative or zero per-trade Sharpe)")
    elif not trade_results['mintrl_reached']:
        log(f"  MinTRL NOT reached: need {mintrl_t:.0f} trades, have {trade_results['n_trades']}")
    else:
        log(f"  MinTRL reached: need {mintrl_t:.0f} trades, have {trade_results['n_trades']}")

    log(f"\n  Bootstrap 95% CI: [{bootstrap_results['ci_95_lower']:.4f}, {bootstrap_results['ci_95_upper']:.4f}]")
    log(f"  Bootstrap {'CONFIRMS' if bootstrap_results['significant_at_5pct'] else 'DOES NOT CONFIRM'} "
        f"significance at 5% level")
    log(f"  {bootstrap_results['pct_positive']:.1f}% of bootstrap resamples have positive Sharpe")

    # ── Save ───────────────────────────────────────────────────────────
    summary = {
        'description': 'PSR/MinTRL verification: daily equity vs per-trade R returns',
        'trade_log': str(TRADE_LOG),
        'task1_daily_equity': daily_results,
        'task2_per_trade_r': trade_results,
        'task3_comparison': comparison,
        'task4_block_bootstrap': bootstrap_results,
    }

    # Convert numpy types for JSON serialization
    def make_serializable(obj):
        if isinstance(obj, dict):
            return {k: make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, (np.bool_, np.integer)):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        return obj

    summary = make_serializable(summary)

    summary_path = RESULTS_DIR / "psr_verification_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    log(f"\n  Summary saved: {summary_path}")

    log_path = RESULTS_DIR / "psr_verification_log.txt"
    with open(log_path, "w") as f:
        f.write("\n".join(LOG_LINES))
    log(f"  Log saved: {log_path}")


if __name__ == "__main__":
    main()
