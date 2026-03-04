"""
CSCV / PBO Analysis — Probability of Backtest Overfitting

Implements the Combinatorially Symmetric Cross-Validation (CSCV) framework
from Bailey, Borwein, López de Prado, Zhu (2015) to estimate the
Probability of Backtest Overfitting (PBO).

STEP 1: Build trials matrix M (T days × N strategies)
  - Run 16 distinct strategy configs over the full period
  - Extract DAILY portfolio returns for each
  - Matrix M: rows = trading days, columns = strategy configs

STEP 2: CSCV procedure (S=8 blocks, C(8,4)=70 splits)
  - For each split: find IS-best strategy, measure OOS performance
  - PBO = fraction of splits where IS-best has OOS Sharpe < 0

STEP 3: Report PBO, logit distribution, performance degradation
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

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.core.intraday_levels import IntradayLevelConfig
from backtester.optimizer import load_ticker_data

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']
FULL_START = '2025-02-10'
FULL_END = '2026-01-31'
CAPITAL = 100_000.0

# CSCV parameters
S = 8  # number of sub-blocks (must be even)

LOG = []


def log(msg=''):
    LOG.append(msg)
    print(msg)


# ═══════════════════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS (for regime post-filters)
# ═══════════════════════════════════════════════════════════════════════════

def compute_atr_series(daily, period=14):
    high = daily['High'].values
    low = daily['Low'].values
    close = daily['Close'].values
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return pd.Series(tr, index=daily.index).rolling(window=period, min_periods=1).mean()


def compute_adx(daily, period=14):
    high = daily['High'].values.astype(float)
    low = daily['Low'].values.astype(float)
    close = daily['Close'].values.astype(float)
    n = len(high)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]),
                     abs(low[i] - close[i - 1]))

    def wilder_smooth(arr, p):
        out = np.zeros(len(arr))
        if p < len(arr):
            out[p] = np.sum(arr[1:p + 1])
            for i in range(p + 1, len(arr)):
                out[i] = out[i - 1] - out[i - 1] / p + arr[i]
        return out

    smooth_tr = wilder_smooth(tr, period)
    smooth_plus_dm = wilder_smooth(plus_dm, period)
    smooth_minus_dm = wilder_smooth(minus_dm, period)
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    dx = np.zeros(n)
    for i in range(period, n):
        if smooth_tr[i] > 0:
            plus_di[i] = 100 * smooth_plus_dm[i] / smooth_tr[i]
            minus_di[i] = 100 * smooth_minus_dm[i] / smooth_tr[i]
        di_sum = plus_di[i] + minus_di[i]
        if di_sum > 0:
            dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / di_sum
    adx = np.zeros(n)
    start = 2 * period
    if start < n:
        adx[start] = np.mean(dx[period:start + 1])
        for i in range(start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return pd.Series(adx, index=daily.index)


def aggregate_m5_to_daily(m5_df):
    df = m5_df.copy()
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    minutes = df['Datetime'].dt.hour * 60 + df['Datetime'].dt.minute
    rth_mask = (minutes >= 16 * 60 + 30) & (minutes < 23 * 60)
    rth = df[rth_mask].copy()
    rth['Date'] = rth['Datetime'].dt.date
    daily = rth.groupby('Date').agg(
        Open=('Open', 'first'), High=('High', 'max'),
        Low=('Low', 'min'), Close=('Close', 'last'),
        Volume=('Volume', 'sum'),
    ).reset_index()
    daily['Date'] = pd.to_datetime(daily['Date'])
    return daily


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def build_config(name, params):
    """Build BacktestConfig from a flat parameter dict."""
    p = params

    # Determine if this config uses intraday levels / tiers
    use_tiers = p.get('use_tiers', True)

    intraday_cfg = None
    tier_cfg = None
    if use_tiers:
        intraday_cfg = IntradayLevelConfig(
            fractal_depth_m5=5, fractal_depth_h1=3, enable_h1=True,
            min_target_r=1.0, lookback_bars=1000,
        )
        tier_cfg = {
            'mode': p.get('tier_mode', '2tier_trail'),
            't1_pct': p.get('t1_pct', 0.30),
            'trail_factor': p.get('trail_factor', 0.7),
            'trail_activation_r': p.get('trail_activation_r', 0.0),
            'min_rr': p.get('tier_min_rr', 2.0),
        }

    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=p.get('fractal_depth', 10),
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=p.get('min_level_score', 5),
            cross_count_invalidate=p.get('cross_count_invalidate', 5),
            cross_count_window=p.get('cross_count_window', 30),
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=p.get('tail_ratio_min', 0.15),
            lp2_engulfing_required=True,
            clp_min_bars=3,
            clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=p.get('atr_block_threshold', 0.20),
            atr_entry_threshold=p.get('atr_entry_threshold', 0.60),
            enable_volume_filter=p.get('enable_volume_filter', True),
            enable_time_filter=p.get('enable_time_filter', True),
            enable_squeeze_filter=p.get('enable_squeeze_filter', True),
            open_delay_minutes=p.get('open_delay_minutes', 5),
            earnings_dates={},
        ),
        risk_config=RiskManagerConfig(
            min_rr=p.get('min_rr', 2.0),
            max_stop_atr_pct=p.get('max_stop_atr_pct', 0.15),
            capital=CAPITAL,
            risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02,
            partial_tp_at_r=2.0,
            partial_tp_pct=0.50,
        ),
        intraday_config=intraday_cfg,
        tier_config=tier_cfg,
        direction_filter=None,
        name=name,
    )


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY DEFINITIONS (16 distinct configs)
# ═══════════════════════════════════════════════════════════════════════════

def define_strategies():
    """Define all strategy variants for the trials matrix.

    We need N >= 8 columns.  We use 16 strategies spanning:
      - Phase 2.5 baseline (all filters)
      - Config A (simplified)
      - Config C (minimal)
      - Nuclear (no filters)
      - Phase 2.2 parameter variants (FD, ATR, RR, stop, sawing)

    Each entry: {name, params, adx_thresh, atr_ratio_thresh}
    where adx_thresh/atr_ratio_thresh are regime post-filters (None = disabled).
    """
    strategies = []

    # ── Phase 2.5/2.6 configs ─────────────────────────────────────────

    # S0: CONFIG A (Simplified) — our candidate
    strategies.append({
        'name': 'S00_ConfigA_Simplified',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.0, 'atr_entry_threshold': 0.0,
            'enable_volume_filter': False, 'enable_squeeze_filter': False,
            'enable_time_filter': True, 'open_delay_minutes': 5,
            'min_rr': 0.01, 'max_stop_atr_pct': 0.15,
            'cross_count_invalidate': 5, 'cross_count_window': 30,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # S1: BASELINE (all filters on)
    strategies.append({
        'name': 'S01_Baseline_AllFilters',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60,
            'enable_volume_filter': True, 'enable_squeeze_filter': True,
            'enable_time_filter': True, 'open_delay_minutes': 5,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.15,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # S2: Config C (minimal: nuclear + same-level limit)
    strategies.append({
        'name': 'S02_ConfigC_Minimal',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.0, 'atr_entry_threshold': 0.0,
            'enable_volume_filter': False, 'enable_squeeze_filter': False,
            'enable_time_filter': False, 'open_delay_minutes': 0,
            'min_rr': 0.01, 'max_stop_atr_pct': 0.15,
        },
        'adx_thresh': None, 'atr_ratio_thresh': None,
    })

    # S3: Nuclear (all filters off)
    strategies.append({
        'name': 'S03_Nuclear',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.0, 'atr_entry_threshold': 0.0,
            'enable_volume_filter': False, 'enable_squeeze_filter': False,
            'enable_time_filter': False, 'open_delay_minutes': 0,
            'min_rr': 0.01, 'max_stop_atr_pct': 0.15,
            'cross_count_invalidate': 999,
        },
        'adx_thresh': None, 'atr_ratio_thresh': None,
    })

    # ── Phase 2.2 Fractal Depth variants ──────────────────────────────

    # S4: FD=3
    strategies.append({
        'name': 'S04_FD3',
        'params': {
            'fractal_depth': 3, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.15,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # S5: FD=5
    strategies.append({
        'name': 'S05_FD5',
        'params': {
            'fractal_depth': 5, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.15,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # S6: FD=7
    strategies.append({
        'name': 'S06_FD7',
        'params': {
            'fractal_depth': 7, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.15,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # ── ATR threshold variants ────────────────────────────────────────

    # S7: ATR high (strict entry)
    strategies.append({
        'name': 'S07_ATR_high',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.30, 'atr_entry_threshold': 0.80,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.15,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # S8: ATR low (permissive entry)
    strategies.append({
        'name': 'S08_ATR_low',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.10, 'atr_entry_threshold': 0.40,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.15,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # ── R:R and stop variants ─────────────────────────────────────────

    # S9: RR=3.0 (strict)
    strategies.append({
        'name': 'S09_RR3',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60,
            'min_rr': 3.0, 'max_stop_atr_pct': 0.15,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # S10: Stop=0.10 (tighter stop)
    strategies.append({
        'name': 'S10_Stop010',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.10,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # S11: Stop=0.20 (wider stop)
    strategies.append({
        'name': 'S11_Stop020',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.20,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # ── Sawing / same-level variants ──────────────────────────────────

    # S12: Tight sawing (3/20)
    strategies.append({
        'name': 'S12_Saw_3_20',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.15,
            'cross_count_invalidate': 3, 'cross_count_window': 20,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # ── Tail ratio variants ───────────────────────────────────────────

    # S13: Tail=0.10 (more permissive)
    strategies.append({
        'name': 'S13_Tail010',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.10,
            'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.15,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # S14: Tail=0.20 (stricter)
    strategies.append({
        'name': 'S14_Tail020',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.20,
            'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.15,
        },
        'adx_thresh': 27, 'atr_ratio_thresh': 1.3,
    })

    # ── Regime filter variants ────────────────────────────────────────

    # S15: No regime filters (ADX/ATR expansion off)
    strategies.append({
        'name': 'S15_NoRegime',
        'params': {
            'fractal_depth': 10, 'tail_ratio_min': 0.15,
            'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60,
            'min_rr': 2.0, 'max_stop_atr_pct': 0.15,
        },
        'adx_thresh': None, 'atr_ratio_thresh': None,
    })

    return strategies


# ═══════════════════════════════════════════════════════════════════════════
# DAILY RETURNS EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

def run_strategy_get_daily_pnl(config, tickers, start_date, end_date,
                                daily_data, adx_thresh=None,
                                atr_ratio_thresh=None):
    """Run a strategy and return a dict of {date_str: daily_pnl}."""
    daily_pnl = {}

    for ticker in tickers:
        m5_df = load_ticker_data(ticker)
        bt = Backtester(config)
        result = bt.run(m5_df, start_date=start_date, end_date=end_date)

        for trade in result.trades:
            if trade.exit_time is None:
                continue

            # Apply regime post-filters
            entry_date = trade.entry_time.normalize().date()

            if adx_thresh is not None and ticker in daily_data:
                d = daily_data[ticker]
                entry_ts = pd.Timestamp(entry_date)
                prior = d[d['Date'] <= entry_ts]
                if not prior.empty:
                    adx_val = prior['ADX'].iloc[-1]
                    if adx_val > 0 and adx_val > adx_thresh:
                        continue  # blocked by ADX filter
                else:
                    continue

            if atr_ratio_thresh is not None and ticker in daily_data:
                d = daily_data[ticker]
                entry_ts = pd.Timestamp(entry_date)
                prior = d[d['Date'] <= entry_ts]
                if not prior.empty:
                    ratio = prior['ATR_ratio_5_20'].iloc[-1]
                    if ratio > atr_ratio_thresh:
                        continue  # blocked by ATR ratio filter
                else:
                    continue

            # Attribute P&L to the exit date
            exit_date_str = trade.exit_time.strftime('%Y-%m-%d')
            daily_pnl[exit_date_str] = daily_pnl.get(exit_date_str, 0.0) + trade.pnl

    return daily_pnl


# ═══════════════════════════════════════════════════════════════════════════
# CSCV ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def sharpe_ratio(returns):
    """Compute (unannualized) Sharpe ratio from a return array."""
    if len(returns) < 2:
        return 0.0
    std = np.std(returns, ddof=1)
    if std == 0:
        return 0.0
    return np.mean(returns) / std


def run_cscv(M, S=8):
    """Run Combinatorially Symmetric Cross-Validation.

    Args:
        M: numpy array of shape (T, N) — daily returns for N strategies over T days
        S: number of sub-blocks (must be even)

    Returns:
        dict with PBO, logits, IS/OOS Sharpe pairs, etc.
    """
    T, N = M.shape
    half_S = S // 2

    # Split into S equal-sized blocks
    block_size = T // S
    # Trim to make exactly S equal blocks
    M_trimmed = M[:block_size * S, :]
    blocks = [M_trimmed[i * block_size:(i + 1) * block_size, :] for i in range(S)]

    # Generate all C(S, S/2) combinatorial splits
    block_indices = list(range(S))
    all_splits = list(combinations(block_indices, half_S))

    n_splits = len(all_splits)
    log(f"    CSCV: T={T}, N={N}, S={S}, block_size={block_size}, "
        f"splits=C({S},{half_S})={n_splits}")

    logits = []
    is_sharpes = []
    oos_sharpes = []
    oos_negative_count = 0
    is_best_indices = []

    for split_idx, is_blocks in enumerate(all_splits):
        oos_blocks = tuple(b for b in block_indices if b not in is_blocks)

        # Assemble IS and OOS matrices
        is_data = np.vstack([blocks[b] for b in is_blocks])   # (half_T, N)
        oos_data = np.vstack([blocks[b] for b in oos_blocks])  # (half_T, N)

        # Compute IS Sharpe for each strategy
        is_sr = np.array([sharpe_ratio(is_data[:, j]) for j in range(N)])

        # Find IS-best strategy
        is_best = np.argmax(is_sr)
        is_best_indices.append(is_best)
        is_sharpes.append(is_sr[is_best])

        # Compute OOS Sharpe for the IS-best strategy
        oos_sr_best = sharpe_ratio(oos_data[:, is_best])
        oos_sharpes.append(oos_sr_best)

        # Compute OOS Sharpes for ALL strategies (for ranking)
        oos_sr_all = np.array([sharpe_ratio(oos_data[:, j]) for j in range(N)])

        # Rank of IS-best in OOS (1 = worst, N = best)
        oos_rank = np.sum(oos_sr_all <= oos_sr_best)  # rank from bottom

        # Logit: lambda = ln(rank / (N - rank))
        # Clip to avoid log(0)
        rank_ratio = max(oos_rank, 0.5) / max(N - oos_rank, 0.5)
        logit = np.log(rank_ratio)
        logits.append(logit)

        # PBO count: IS-best has OOS Sharpe < 0?
        if oos_sr_best < 0:
            oos_negative_count += 1

    pbo = oos_negative_count / n_splits
    logits = np.array(logits)
    is_sharpes = np.array(is_sharpes)
    oos_sharpes = np.array(oos_sharpes)

    return {
        'pbo': pbo,
        'n_splits': n_splits,
        'logits': logits,
        'is_sharpes': is_sharpes,
        'oos_sharpes': oos_sharpes,
        'oos_negative_count': oos_negative_count,
        'is_best_indices': is_best_indices,
        'block_size': block_size,
        'T_used': block_size * S,
    }


def run_cscv_for_subset(M, strategy_names, focus_idx, S=8):
    """Run CSCV and also compute metrics focused on one strategy."""
    result = run_cscv(M, S)

    # How often was the focus strategy selected as IS-best?
    focus_selected = sum(1 for i in result['is_best_indices'] if i == focus_idx)

    # When focus strategy was IS-best, what was its OOS Sharpe?
    focus_oos_sharpes = [result['oos_sharpes'][k]
                         for k, i in enumerate(result['is_best_indices'])
                         if i == focus_idx]

    result['focus_strategy'] = strategy_names[focus_idx]
    result['focus_idx'] = focus_idx
    result['focus_selected_count'] = focus_selected
    result['focus_selected_pct'] = focus_selected / result['n_splits'] * 100
    result['focus_oos_sharpes'] = np.array(focus_oos_sharpes) if focus_oos_sharpes else np.array([])

    return result


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    total_start = time.time()

    log("=" * 90)
    log("  CSCV / PBO ANALYSIS — Probability of Backtest Overfitting")
    log("  Bailey, Borwein, López de Prado, Zhu (2015)")
    log("=" * 90)
    log(f"  Focus strategy: Config A (Simplified Filter Chain)")
    log(f"  Tickers: {', '.join(TICKERS)}  |  Period: {FULL_START} -> {FULL_END}")
    log(f"  CSCV blocks: S={S}  |  Splits: C({S},{S//2}) = "
        f"{len(list(combinations(range(S), S//2)))}")
    log("")

    # ── Step 1: Precompute daily indicators for regime post-filters ───
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

    # ── Step 2: Define strategies and generate daily returns ──────────
    strategies = define_strategies()
    N = len(strategies)
    log(f"\n  Step 2: Running {N} strategy variants to build trials matrix...")

    # Collect all unique trading dates across all strategies
    all_daily_pnls = []
    strategy_names = []

    for si, strat in enumerate(strategies):
        strat_start = time.time()
        config = build_config(strat['name'], strat['params'])

        daily_pnl = run_strategy_get_daily_pnl(
            config, TICKERS, FULL_START, FULL_END,
            daily_data,
            adx_thresh=strat.get('adx_thresh'),
            atr_ratio_thresh=strat.get('atr_ratio_thresh'),
        )

        total_pnl = sum(daily_pnl.values())
        n_trade_days = sum(1 for v in daily_pnl.values() if v != 0)
        elapsed = time.time() - strat_start

        log(f"    [{si:>2}] {strat['name']:<30} "
            f"P&L=${total_pnl:>8,.0f}  trade_days={n_trade_days:>3}  "
            f"[{elapsed:.1f}s]")

        all_daily_pnls.append(daily_pnl)
        strategy_names.append(strat['name'])

    # ── Step 3: Build the trials matrix M (T × N) ────────────────────
    log(f"\n  Step 3: Building trials matrix M...")

    # Union of all dates
    all_dates = set()
    for dp in all_daily_pnls:
        all_dates.update(dp.keys())
    all_dates = sorted(all_dates)
    T = len(all_dates)
    log(f"    Total trading days: {T}")

    # Build matrix: rows = days, columns = strategies
    # Each cell = daily P&L as return on capital
    M = np.zeros((T, N))
    for j, dp in enumerate(all_daily_pnls):
        for i, date_str in enumerate(all_dates):
            M[i, j] = dp.get(date_str, 0.0) / CAPITAL

    # Summary stats per strategy
    log(f"\n    Strategy return statistics:")
    log(f"    {'#':>4} {'Strategy':<30} {'Mean':>10} {'Std':>10} {'SR':>8} {'Total%':>8}")
    log(f"    {'─' * 78}")
    for j in range(N):
        col = M[:, j]
        sr = sharpe_ratio(col)
        log(f"    {j:>4} {strategy_names[j]:<30} "
            f"{np.mean(col)*100:>9.4f}% {np.std(col)*100:>9.4f}% "
            f"{sr:>7.3f} {np.sum(col)*100:>7.3f}%")

    # ── Step 4: Run CSCV ─────────────────────────────────────────────
    log(f"\n  Step 4: Running CSCV (S={S})...")

    focus_idx = 0  # S00_ConfigA_Simplified
    cscv = run_cscv_for_subset(M, strategy_names, focus_idx, S=S)

    # ── Step 5: Report ────────────────────────────────────────────────
    log(f"\n{'=' * 90}")
    log(f"  CSCV / PBO RESULTS")
    log(f"{'=' * 90}")

    # 1. PBO value
    pbo = cscv['pbo']
    log(f"\n  1. PROBABILITY OF BACKTEST OVERFITTING (PBO)")
    log(f"  {'─' * 60}")
    log(f"     PBO = {pbo:.4f} ({pbo*100:.1f}%)")
    log(f"     OOS-negative splits: {cscv['oos_negative_count']} / {cscv['n_splits']}")

    if pbo < 0.10:
        interpretation = "LIKELY REAL EDGE — low overfitting risk"
    elif pbo < 0.30:
        interpretation = "SOME OVERFITTING RISK — use caution"
    elif pbo < 0.50:
        interpretation = "SERIOUS OVERFITTING RISK — edge may be illusory"
    else:
        interpretation = "PROBABLY OVERFITTED — IS performance likely inflated"
    log(f"     Interpretation: {interpretation}")

    # 2. Logit distribution
    logits = cscv['logits']
    log(f"\n  2. LOGIT DISTRIBUTION (lambda)")
    log(f"  {'─' * 60}")
    log(f"     Mean logit:    {np.mean(logits):>8.4f}")
    log(f"     Median logit:  {np.median(logits):>8.4f}")
    log(f"     Std logit:     {np.std(logits):>8.4f}")
    log(f"     Min logit:     {np.min(logits):>8.4f}")
    log(f"     Max logit:     {np.max(logits):>8.4f}")

    # Logit histogram (text-based)
    log(f"\n     Logit histogram:")
    bins = np.linspace(np.min(logits) - 0.1, np.max(logits) + 0.1, 11)
    counts, edges = np.histogram(logits, bins=bins)
    max_count = max(counts) if max(counts) > 0 else 1
    for i in range(len(counts)):
        bar = '█' * int(counts[i] / max_count * 40)
        log(f"     [{edges[i]:>6.2f}, {edges[i+1]:>6.2f}): {counts[i]:>3} {bar}")

    log(f"\n     Positive logits (IS-best ranks well OOS): "
        f"{np.sum(logits > 0)} / {len(logits)} ({np.sum(logits > 0)/len(logits)*100:.1f}%)")
    log(f"     Negative logits (IS-best ranks poorly OOS): "
        f"{np.sum(logits <= 0)} / {len(logits)} ({np.sum(logits <= 0)/len(logits)*100:.1f}%)")

    # 3. Performance degradation
    is_sr = cscv['is_sharpes']
    oos_sr = cscv['oos_sharpes']

    log(f"\n  3. PERFORMANCE DEGRADATION (IS vs OOS Sharpe)")
    log(f"  {'─' * 60}")
    log(f"     IS Sharpe  — Mean: {np.mean(is_sr):.4f}, Median: {np.median(is_sr):.4f}")
    log(f"     OOS Sharpe — Mean: {np.mean(oos_sr):.4f}, Median: {np.median(oos_sr):.4f}")

    degradation = np.mean(is_sr) - np.mean(oos_sr)
    if np.mean(is_sr) != 0:
        degradation_pct = degradation / abs(np.mean(is_sr)) * 100
    else:
        degradation_pct = 0.0
    log(f"     Mean degradation: {degradation:.4f} ({degradation_pct:.1f}%)")

    # Correlation between IS and OOS Sharpe
    if len(is_sr) > 2:
        corr, p_val = scipy_stats.pearsonr(is_sr, oos_sr)
        log(f"     IS-OOS correlation: r={corr:.4f} (p={p_val:.4f})")
        if corr > 0.3:
            log(f"     >> Positive correlation — IS performance has SOME predictive value")
        elif corr > 0:
            log(f"     >> Weak positive correlation — limited predictive value")
        else:
            log(f"     >> Zero or negative correlation — IS performance is NOT predictive")

    # Scatter summary: IS vs OOS Sharpe (text table)
    log(f"\n     IS vs OOS Sharpe scatter (first 20 splits):")
    log(f"     {'Split':>6} {'IS SR':>8} {'OOS SR':>8} {'Degrad':>8} {'Best Strat':>4}")
    log(f"     {'─' * 42}")
    for k in range(min(20, len(is_sr))):
        deg = is_sr[k] - oos_sr[k]
        log(f"     {k+1:>6} {is_sr[k]:>8.4f} {oos_sr[k]:>8.4f} {deg:>8.4f} "
            f"S{cscv['is_best_indices'][k]:>02}")

    # 4. Stochastic dominance check
    log(f"\n  4. STOCHASTIC DOMINANCE CHECK")
    log(f"  {'─' * 60}")

    # Distribution of OOS returns from IS-optimal strategies
    is_optimal_oos_returns = []
    for k in range(len(cscv['is_best_indices'])):
        is_blocks = list(combinations(range(S), S // 2))[k]
        oos_blocks = [b for b in range(S) if b not in is_blocks]
        block_size = cscv['block_size']
        M_trimmed = M[:block_size * S, :]
        oos_data = np.vstack([M_trimmed[b * block_size:(b + 1) * block_size, :]
                              for b in oos_blocks])
        best_idx = cscv['is_best_indices'][k]
        is_optimal_oos_returns.extend(oos_data[:, best_idx].tolist())

    # Overall OOS return distribution (all strategies, all splits)
    overall_oos_returns = M_trimmed.flatten().tolist()

    is_opt_mean = np.mean(is_optimal_oos_returns)
    overall_mean = np.mean(overall_oos_returns)
    ks_stat, ks_p = scipy_stats.ks_2samp(is_optimal_oos_returns, overall_oos_returns)

    log(f"     IS-optimal OOS mean return: {is_opt_mean*100:.5f}%")
    log(f"     Overall OOS mean return:    {overall_mean*100:.5f}%")
    log(f"     KS test: stat={ks_stat:.4f}, p={ks_p:.4f}")

    if is_opt_mean > overall_mean and ks_p < 0.05:
        log(f"     >> IS-optimal DOMINATES overall — selection adds value")
    elif is_opt_mean > overall_mean:
        log(f"     >> IS-optimal slightly better but NOT significant")
    else:
        log(f"     >> IS-optimal does NOT dominate — selection is not adding value")

    # 5. Focus strategy analysis (Config A)
    log(f"\n  5. CONFIG A FOCUS ANALYSIS")
    log(f"  {'─' * 60}")
    log(f"     Focus strategy: {cscv['focus_strategy']}")
    log(f"     Selected as IS-best: {cscv['focus_selected_count']} / {cscv['n_splits']} "
        f"({cscv['focus_selected_pct']:.1f}%)")

    if len(cscv['focus_oos_sharpes']) > 0:
        log(f"     When selected, OOS Sharpe:")
        log(f"       Mean:   {np.mean(cscv['focus_oos_sharpes']):.4f}")
        log(f"       Median: {np.median(cscv['focus_oos_sharpes']):.4f}")
        log(f"       Min:    {np.min(cscv['focus_oos_sharpes']):.4f}")
        log(f"       Max:    {np.max(cscv['focus_oos_sharpes']):.4f}")
        log(f"       OOS < 0: {np.sum(cscv['focus_oos_sharpes'] < 0)} / "
            f"{len(cscv['focus_oos_sharpes'])}")
    else:
        log(f"     Config A was NEVER selected as IS-best across any split")
        log(f"     This means other strategies always had higher IS Sharpe")

    # Full-sample SR for Config A
    config_a_sr = sharpe_ratio(M[:, focus_idx])
    log(f"     Full-sample Sharpe ratio: {config_a_sr:.4f}")

    # 6. Config A vs Baseline comparison
    baseline_idx = 1  # S01_Baseline_AllFilters
    log(f"\n  6. CONFIG A vs BASELINE PBO COMPARISON")
    log(f"  {'─' * 60}")

    # How often each was selected as IS-best
    config_a_count = sum(1 for i in cscv['is_best_indices'] if i == focus_idx)
    baseline_count = sum(1 for i in cscv['is_best_indices'] if i == baseline_idx)
    log(f"     Config A selected as IS-best:  {config_a_count} / {cscv['n_splits']}")
    log(f"     Baseline selected as IS-best:  {baseline_count} / {cscv['n_splits']}")

    config_a_full_sr = sharpe_ratio(M[:, focus_idx])
    baseline_full_sr = sharpe_ratio(M[:, baseline_idx])
    log(f"     Config A full-sample SR:  {config_a_full_sr:.4f}")
    log(f"     Baseline full-sample SR:  {baseline_full_sr:.4f}")

    # Which strategy is IS-best most often?
    from collections import Counter
    best_counts = Counter(cscv['is_best_indices'])
    log(f"\n     Most frequently IS-best strategies:")
    for idx, count in best_counts.most_common(5):
        log(f"       {strategy_names[idx]}: {count}/{cscv['n_splits']} ({count/cscv['n_splits']*100:.1f}%)")

    # ── VERDICT ───────────────────────────────────────────────────────
    log(f"\n{'=' * 90}")
    log(f"  VERDICT")
    log(f"{'=' * 90}")

    log(f"\n  PBO = {pbo:.2%}")
    if pbo < 0.10:
        log(f"  The probability of backtest overfitting is LOW ({pbo:.1%}).")
        log(f"  The strategy selection process has a {100-pbo*100:.0f}% chance of producing")
        log(f"  a strategy that performs positively out-of-sample.")
    elif pbo < 0.30:
        log(f"  There is MODERATE overfitting risk ({pbo:.1%}).")
        log(f"  Roughly {pbo*100:.0f}% of the time, the IS-best strategy loses money OOS.")
    elif pbo < 0.50:
        log(f"  There is SERIOUS overfitting risk ({pbo:.1%}).")
        log(f"  The IS-selected strategy fails OOS about {pbo*100:.0f}% of the time.")
    else:
        log(f"  The strategy is LIKELY OVERFITTED ({pbo:.1%}).")
        log(f"  More than half the time, IS-optimization picks an OOS loser.")

    log(f"\n  Mean performance degradation: {degradation_pct:.1f}%")
    if abs(degradation_pct) < 30:
        log(f"  Degradation is moderate — performance is relatively stable IS→OOS.")
    elif degradation_pct < 60:
        log(f"  Significant degradation — IS performance overstates OOS by ~{degradation_pct:.0f}%.")
    else:
        log(f"  Severe degradation — IS performance is heavily inflated.")

    # Degrees of freedom note
    log(f"\n  DEGREES OF FREEDOM NOTE:")
    log(f"  Config A (simplified, 2 filters) should have lower PBO than")
    log(f"  Baseline (all filters, more parameters). Fewer knobs = less room")
    log(f"  for overfitting. Observed: Config A selected {config_a_count}x vs "
        f"Baseline {baseline_count}x as IS-best.")

    elapsed = time.time() - total_start
    log(f"\n{'=' * 90}")
    log(f"  COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"{'=' * 90}")

    # ── Save results ──────────────────────────────────────────────────
    report_path = os.path.join(RESULTS_DIR, 'cscv_pbo_analysis.txt')
    with open(report_path, 'w') as f:
        f.write('\n'.join(LOG))
    log(f"\n  Report saved: {report_path}")

    json_data = {
        'phase': 'CSCV/PBO',
        'description': 'Probability of Backtest Overfitting via CSCV',
        'method': 'Bailey, Borwein, López de Prado, Zhu (2015)',
        'parameters': {
            'S': S,
            'N_strategies': N,
            'T_days': T,
            'T_used': cscv['T_used'],
            'block_size': cscv['block_size'],
            'n_splits': cscv['n_splits'],
        },
        'results': {
            'pbo': float(pbo),
            'oos_negative_count': int(cscv['oos_negative_count']),
            'logit_mean': float(np.mean(logits)),
            'logit_median': float(np.median(logits)),
            'logit_std': float(np.std(logits)),
            'is_sharpe_mean': float(np.mean(is_sr)),
            'oos_sharpe_mean': float(np.mean(oos_sr)),
            'degradation_pct': float(degradation_pct),
            'is_oos_correlation': float(corr) if len(is_sr) > 2 else None,
        },
        'focus_strategy': {
            'name': cscv['focus_strategy'],
            'full_sample_sr': float(config_a_full_sr),
            'selected_as_is_best_count': int(cscv['focus_selected_count']),
            'selected_as_is_best_pct': float(cscv['focus_selected_pct']),
        },
        'strategy_names': strategy_names,
        'strategy_full_sample_sr': [float(sharpe_ratio(M[:, j])) for j in range(N)],
    }

    json_path = os.path.join(RESULTS_DIR, 'cscv_pbo_analysis.json')
    with open(json_path, 'w') as f:
        json.dump(json_data, f, indent=2)
    log(f"  JSON saved: {json_path}")


if __name__ == '__main__':
    main()
