"""
Deflated Sharpe Ratio (DSR) & Minimum Track Record Length (MinTRL)
per López de Prado (2014), "The Deflated Sharpe Ratio: Correcting for
Selection Bias, Backtest Overfitting, and Non-Normality."

Applied to Phase 2.5 OOS walk-forward results:
  FD=10 + ADX<=27 + ATR_ratio<=1.3
  54 trades across 6 windows, $100K capital
"""

import numpy as np
from scipy import stats


# ═══════════════════════════════════════════════════════════════════════════
# INPUT DATA — Phase 2.5 OOS Walk-Forward Results
# ═══════════════════════════════════════════════════════════════════════════

WINDOW_PNL = np.array([144.0, 400.0, -532.0, 1238.0, 5288.0, -2183.0])
WINDOW_TRADES = np.array([9, 7, 2, 6, 6, 14])  # approximate per-window trade counts (54 total)
TOTAL_TRADES = 54
CAPITAL = 100_000.0
TOTAL_PNL = WINDOW_PNL.sum()  # 4355.0
NUM_TRIALS = 50  # 23 param experiments + 27 walk-forward runs
BENCHMARK_SR = 0.0  # null hypothesis: no edge (random)
CONFIDENCE = 0.95  # 95% significance level


# ═══════════════════════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def sharpe_ratio(returns, periods_per_year=1):
    """Annualized Sharpe ratio from a return series.

    For trade-level returns with no natural time frequency,
    periods_per_year=1 gives the raw (unannualized) SR.
    For daily returns, use periods_per_year=252.
    """
    if len(returns) < 2 or np.std(returns, ddof=1) == 0:
        return 0.0
    return (np.mean(returns) / np.std(returns, ddof=1)) * np.sqrt(periods_per_year)


def probabilistic_sharpe_ratio(sr_hat, sr_benchmark, T, skew, kurt):
    """PSR — probability that true SR exceeds a benchmark, adjusted
    for non-normality.

    López de Prado (2014), Eq. 4:
      PSR(SR*) = Φ( (SR_hat - SR*) * sqrt(T-1) /
                     sqrt(1 - γ3·SR_hat + ((γ4-1)/4)·SR_hat²) )

    Args:
        sr_hat:       observed Sharpe ratio (not annualized)
        sr_benchmark: benchmark SR to beat (SR*)
        T:            number of observations (trades or returns)
        skew:         skewness of returns (γ3)
        kurt:         excess kurtosis of returns (γ4, Fisher definition)
    Returns:
        PSR value in [0, 1] — probability true SR > benchmark
    """
    numerator = (sr_hat - sr_benchmark) * np.sqrt(T - 1)
    denominator = np.sqrt(1.0 - skew * sr_hat + ((kurt - 1) / 4.0) * sr_hat ** 2)
    if denominator <= 0:
        return 0.0
    z = numerator / denominator
    return stats.norm.cdf(z)


def expected_max_sr(N, T, skew, kurt, sr_std=1.0):
    """Expected maximum Sharpe ratio from N independent trials.

    López de Prado (2014), Eq. 11 — approximation based on
    extreme value theory (Euler-Mascheroni constant):
      E[max(SR)] ≈ σ(SR) · { (1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e)) }

    where σ(SR) = sqrt( V[SR_hat] ) is the std of the SR estimator:
      V[SR_hat] = (1 - γ3·SR + ((γ4-1)/4)·SR²) / (T-1)

    For the null (SR=0), this simplifies to:
      V[SR_hat] = (1 + ((γ4-1)/4)·0) / (T-1) = 1/(T-1)

    Args:
        N:      number of independent trials
        T:      number of observations per trial
        skew:   skewness (unused under null SR=0, kept for generality)
        kurt:   excess kurtosis
        sr_std: std of SR estimator; if None, computed from T
    Returns:
        E[max(SR)] — the expected best SR you'd see by chance
    """
    EULER_MASCHERONI = 0.5772156649

    # Std of SR estimator under the null (SR=0)
    sr_var = (1.0 + ((kurt - 1) / 4.0) * 0.0) / (T - 1)
    sr_std = np.sqrt(sr_var)

    if N <= 1:
        return 0.0

    z1 = stats.norm.ppf(1.0 - 1.0 / N)
    z2 = stats.norm.ppf(1.0 - 1.0 / (N * np.e))

    e_max = sr_std * ((1 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2)
    return e_max


def deflated_sharpe_ratio(sr_hat, T, N, skew, kurt):
    """Deflated Sharpe Ratio — PSR evaluated against the expected
    maximum SR from N trials instead of a fixed benchmark.

    DSR = PSR( SR* = E[max(SR)] )

    This answers: "What is the probability that our observed SR
    would still be significant after accounting for the number
    of strategies we tried?"

    Args:
        sr_hat: observed SR (not annualized)
        T:      number of return observations
        N:      number of independent trials/backtests
        skew:   skewness of returns
        kurt:   excess kurtosis of returns
    Returns:
        DSR in [0, 1]
    """
    sr_star = expected_max_sr(N, T, skew, kurt)
    return probabilistic_sharpe_ratio(sr_hat, sr_star, T, skew, kurt)


def min_track_record_length(sr_hat, sr_benchmark, skew, kurt, alpha=0.05):
    """Minimum Track Record Length — the minimum number of observations
    needed for the observed SR to be significant at level α.

    López de Prado (2014), Eq. 8:
      MinTRL = 1 + (1 - γ3·SR + ((γ4-1)/4)·SR²) · (z_α / (SR - SR*))²

    Args:
        sr_hat:       observed SR
        sr_benchmark: benchmark SR (SR*)
        skew:         skewness
        kurt:         excess kurtosis
        alpha:        significance level (default 5%)
    Returns:
        MinTRL (float) — minimum number of observations needed
    """
    if sr_hat <= sr_benchmark:
        return float('inf')  # can never be significant

    z_alpha = stats.norm.ppf(1.0 - alpha)
    variance_factor = 1.0 - skew * sr_hat + ((kurt - 1) / 4.0) * sr_hat ** 2
    min_trl = 1.0 + variance_factor * (z_alpha / (sr_hat - sr_benchmark)) ** 2
    return min_trl


# ═══════════════════════════════════════════════════════════════════════════
# ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def run_analysis():
    print("=" * 72)
    print("  DEFLATED SHARPE RATIO & MINIMUM TRACK RECORD LENGTH")
    print("  López de Prado (2014)")
    print("=" * 72)

    # ── Compute return series ─────────────────────────────────────────
    # Use window-level P&L as percentage returns on capital
    window_returns = WINDOW_PNL / CAPITAL
    T = len(window_returns)  # 6 windows

    print(f"\n  INPUT DATA")
    print(f"  {'─' * 60}")
    print(f"  OOS windows:          {T}")
    print(f"  OOS trades:           {TOTAL_TRADES}")
    print(f"  Capital:              ${CAPITAL:,.0f}")
    print(f"  Total P&L:            ${TOTAL_PNL:,.0f} ({TOTAL_PNL/CAPITAL*100:.2f}%)")
    print(f"  Window P&L:           {[f'${x:+,.0f}' for x in WINDOW_PNL]}")
    print(f"  Window returns (%):   {[f'{r*100:+.3f}' for r in window_returns]}")
    print(f"  Backtest trials (N):  {NUM_TRIALS}")
    print(f"  Benchmark SR:         {BENCHMARK_SR}")

    # ── Return statistics ─────────────────────────────────────────────
    mean_ret = np.mean(window_returns)
    std_ret = np.std(window_returns, ddof=1)
    skew_ret = stats.skew(window_returns, bias=False)
    kurt_ret = stats.kurtosis(window_returns, bias=False)  # excess kurtosis

    print(f"\n  RETURN STATISTICS (window-level)")
    print(f"  {'─' * 60}")
    print(f"  Mean return:          {mean_ret*100:.4f}%")
    print(f"  Std deviation:        {std_ret*100:.4f}%")
    print(f"  Skewness (γ3):        {skew_ret:.4f}")
    print(f"  Excess kurtosis (γ4): {kurt_ret:.4f}")

    # ── 1. Raw Sharpe Ratio ───────────────────────────────────────────
    # Window-level SR (not annualized — no natural time frequency for
    # irregularly-spaced windows)
    sr_raw = sharpe_ratio(window_returns, periods_per_year=1)

    # Annualized approximation: if windows ~ 1 month each, 12 per year
    sr_annualized = sharpe_ratio(window_returns, periods_per_year=12)

    print(f"\n  1. RAW SHARPE RATIO")
    print(f"  {'─' * 60}")
    print(f"  SR (per window):      {sr_raw:.4f}")
    print(f"  SR (annualized, ~12 windows/yr): {sr_annualized:.4f}")

    # ── 2. Probabilistic Sharpe Ratio ─────────────────────────────────
    # PSR vs benchmark SR=0 (can we beat random?)
    psr_zero = probabilistic_sharpe_ratio(sr_raw, BENCHMARK_SR, T, skew_ret, kurt_ret)

    print(f"\n  2. PROBABILISTIC SHARPE RATIO (vs SR*=0)")
    print(f"  {'─' * 60}")
    print(f"  PSR(SR>0):            {psr_zero:.4f} ({psr_zero*100:.2f}%)")
    print(f"  p-value (vs random):  {1 - psr_zero:.4f}")

    # ── 3. Deflated Sharpe Ratio ──────────────────────────────────────
    sr_star = expected_max_sr(NUM_TRIALS, T, skew_ret, kurt_ret)
    dsr = deflated_sharpe_ratio(sr_raw, T, NUM_TRIALS, skew_ret, kurt_ret)

    print(f"\n  3. DEFLATED SHARPE RATIO")
    print(f"  {'─' * 60}")
    print(f"  E[max(SR)] from {NUM_TRIALS} trials: {sr_star:.4f}")
    print(f"  Observed SR:          {sr_raw:.4f}")
    print(f"  SR surplus:           {sr_raw - sr_star:+.4f}")
    print(f"  DSR:                  {dsr:.4f} ({dsr*100:.2f}%)")
    print(f"  p-value (deflated):   {1 - dsr:.4f}")
    print(f"  Significant at 95%?   {'YES' if dsr >= CONFIDENCE else 'NO'}")

    # ── 4. Minimum Track Record Length ────────────────────────────────
    # MinTRL vs benchmark=0 (how many windows to confirm edge?)
    min_trl_zero = min_track_record_length(sr_raw, BENCHMARK_SR, skew_ret, kurt_ret, alpha=0.05)

    # MinTRL vs deflated benchmark E[max(SR)]
    min_trl_deflated = min_track_record_length(sr_raw, sr_star, skew_ret, kurt_ret, alpha=0.05)

    # Convert window-count to approximate trade-count
    avg_trades_per_window = TOTAL_TRADES / T
    min_trades_zero = min_trl_zero * avg_trades_per_window
    min_trades_deflated = min_trl_deflated * avg_trades_per_window

    print(f"\n  4. MINIMUM TRACK RECORD LENGTH (95% confidence)")
    print(f"  {'─' * 60}")
    print(f"  vs SR*=0 (beat random):")
    print(f"    MinTRL:             {min_trl_zero:.1f} windows")
    print(f"    ≈ trades needed:    {min_trades_zero:.0f}")
    print(f"    We have:            {T} windows ({TOTAL_TRADES} trades)")
    print(f"    Sufficient?         {'YES' if T >= min_trl_zero else 'NO'}")
    print()
    print(f"  vs SR*=E[max(SR)] (beat trial-adjusted null):")
    print(f"    MinTRL:             {min_trl_deflated:.1f} windows")
    print(f"    ≈ trades needed:    {min_trades_deflated:.0f}")
    print(f"    We have:            {T} windows ({TOTAL_TRADES} trades)")
    print(f"    Sufficient?         {'YES' if T >= min_trl_deflated else 'NO'}")

    # ── 5. Trade-level analysis (using per-window avg as proxy) ───────
    # Approximate per-trade SR from window data
    # Treating each window's mean trade P&L as the return observation
    per_trade_avg_pnl = WINDOW_PNL / WINDOW_TRADES
    trade_returns = per_trade_avg_pnl / CAPITAL
    T_trades = len(trade_returns)
    sr_trade = sharpe_ratio(trade_returns, periods_per_year=1)
    skew_trade = stats.skew(trade_returns, bias=False)
    kurt_trade = stats.kurtosis(trade_returns, bias=False)

    sr_star_trade = expected_max_sr(NUM_TRIALS, T_trades, skew_trade, kurt_trade)
    dsr_trade = deflated_sharpe_ratio(sr_trade, T_trades, NUM_TRIALS, skew_trade, kurt_trade)
    min_trl_trade = min_track_record_length(sr_trade, sr_star_trade, skew_trade, kurt_trade)
    min_trades_needed = min_trl_trade * avg_trades_per_window

    print(f"\n  5. TRADE-LEVEL PROXY ANALYSIS")
    print(f"  {'─' * 60}")
    print(f"  Per-trade avg P&L by window: {[f'${x:.0f}' for x in per_trade_avg_pnl]}")
    print(f"  Trade-proxy SR:       {sr_trade:.4f}")
    print(f"  Trade-proxy skew:     {skew_trade:.4f}")
    print(f"  Trade-proxy kurtosis: {kurt_trade:.4f}")
    print(f"  E[max(SR)] ({NUM_TRIALS} trials): {sr_star_trade:.4f}")
    print(f"  DSR (trade-proxy):    {dsr_trade:.4f}")

    # ── VERDICT ───────────────────────────────────────────────────────
    print(f"\n{'=' * 72}")
    print(f"  VERDICT")
    print(f"{'=' * 72}")

    significant_psr = psr_zero >= CONFIDENCE
    significant_dsr = dsr >= CONFIDENCE
    sr_below_null = sr_raw < sr_star

    if significant_dsr:
        verdict = "STATISTICALLY SIGNIFICANT"
        detail = (f"DSR={dsr:.2%} exceeds 95% threshold. The observed edge "
                  f"survives correction for {NUM_TRIALS} trials.")
    elif significant_psr and not significant_dsr:
        verdict = "NOT SIGNIFICANT (after deflation)"
        detail = (f"PSR={psr_zero:.2%} beats random, but DSR={dsr:.2%} fails "
                  f"after correcting for {NUM_TRIALS} trials. "
                  f"The edge may be an artifact of overfitting.")
    else:
        verdict = "NOT SIGNIFICANT"
        detail = (f"PSR={psr_zero:.2%}, DSR={dsr:.2%} — both below 95%. "
                  f"Cannot reject the null hypothesis of no edge.")

    print(f"\n  Result: {verdict}")
    print(f"  {detail}")

    if sr_below_null:
        print()
        print(f"  CRITICAL: Observed SR ({sr_raw:.4f}) < E[max(SR)] ({sr_star:.4f})")
        print(f"  Your best result is WORSE than what you'd expect from the best")
        print(f"  of {NUM_TRIALS} random strategies. The entire observed P&L is")
        print(f"  consistent with selection bias — no additional data at this")
        print(f"  SR level can ever make it significant.")

    print()
    print(f"  Do we have enough trades?")

    # MinTRL vs just random (SR*=0)
    if T >= min_trl_zero:
        print(f"    vs random (SR*=0):    YES — {T} windows >= {min_trl_zero:.1f}")
    else:
        needed_trades = min_trl_zero * avg_trades_per_window
        print(f"    vs random (SR*=0):    NO — need {min_trl_zero:.0f} windows "
              f"(~{needed_trades:.0f} trades), have {T} ({TOTAL_TRADES} trades)")

    # MinTRL vs deflated null
    if np.isinf(min_trl_deflated):
        print(f"    vs deflated null:     IMPOSSIBLE at current SR level")
        print(f"                          SR ({sr_raw:.4f}) does not exceed "
              f"trial-adjusted threshold ({sr_star:.4f})")
    elif T >= min_trl_deflated:
        print(f"    vs deflated null:     YES — {T} windows >= {min_trl_deflated:.1f}")
    else:
        needed_trades_d = min_trl_deflated * avg_trades_per_window
        print(f"    vs deflated null:     NO — need {min_trl_deflated:.0f} windows "
              f"(~{needed_trades_d:.0f} trades), have {T} ({TOTAL_TRADES} trades)")

    # ── Summary table ─────────────────────────────────────────────────
    def fmt_trl(v):
        return "∞ (SR below null)" if np.isinf(v) else f"{v:.1f}"

    print()
    print(f"  {'─' * 60}")
    print(f"  Summary:")
    print(f"    Raw SR (annualized):     {sr_annualized:.4f}")
    print(f"    PSR (vs random):         {psr_zero:.4f}  p={1-psr_zero:.4f}")
    print(f"    DSR (vs {NUM_TRIALS}-trial null):  {dsr:.4f}  p={1-dsr:.4f}")
    print(f"    E[max(SR)] ({NUM_TRIALS} trials):  {sr_star:.4f}")
    print(f"    MinTRL (vs random):      {min_trl_zero:.1f} windows (~{min_trl_zero * avg_trades_per_window:.0f} trades)")
    print(f"    MinTRL (deflated):       {fmt_trl(min_trl_deflated)}")
    print(f"    Current record:          {T} windows / {TOTAL_TRADES} trades")
    print(f"  {'─' * 60}")
    print(f"\n  ANSWER: NO — 54 trades across 6 windows is far too few.")
    print(f"  Even ignoring trial correction, you need ~{min_trl_zero * avg_trades_per_window:.0f} trades to beat random.")
    print(f"  After correcting for {NUM_TRIALS} trials, the observed SR=0.29 doesn't")
    print(f"  even clear the selection-bias hurdle of E[max(SR)]={sr_star:.2f}.")
    print()


if __name__ == '__main__':
    run_analysis()
