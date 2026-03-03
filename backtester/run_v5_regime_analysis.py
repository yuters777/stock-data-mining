"""
Phase 5A — Regime Analysis

Computes ADX(14) and ATR regime indicators on D1 bars for all 4 whitelist
tickers. Re-runs v4.1 best config to get per-trade data. Correlates trade
outcomes with regime at entry. Maps WF windows to dominant regime.

Outputs: results/regime_analysis.md
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig, ExitReason
from backtester.core.intraday_levels import IntradayLevelConfig
from backtester.optimizer import load_ticker_data, aggregate_metrics, WalkForwardValidator

# ──────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────

WHITELIST = ['AAPL', 'AMZN', 'GOOGL', 'TSLA']
IS_START = '2025-02-10'
IS_END = '2025-10-01'
OOS_START = '2025-10-01'
OOS_END = '2026-01-31'
FULL_START = '2025-02-10'
FULL_END = '2026-01-31'

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')

# Walk-forward windows (same as v4.1: 3mo train, 1mo test, 8 windows)
WF_WINDOWS = [
    {'id': 1, 'test_start': '2025-05-10', 'test_end': '2025-06-10'},
    {'id': 2, 'test_start': '2025-06-10', 'test_end': '2025-07-10'},
    {'id': 3, 'test_start': '2025-07-10', 'test_end': '2025-08-10'},
    {'id': 4, 'test_start': '2025-08-10', 'test_end': '2025-09-10'},
    {'id': 5, 'test_start': '2025-09-10', 'test_end': '2025-10-10'},
    {'id': 6, 'test_start': '2025-10-10', 'test_end': '2025-11-10'},
    {'id': 7, 'test_start': '2025-11-10', 'test_end': '2025-12-10'},
    {'id': 8, 'test_start': '2025-12-10', 'test_end': '2026-01-10'},
]


# ──────────────────────────────────────────────────────────────────
# v4.1 Best Config
# ──────────────────────────────────────────────────────────────────

def make_v41_config(name='v4.1_best') -> BacktestConfig:
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=10, tolerance_cents=0.05, tolerance_pct=0.001,
            atr_period=5, min_level_score=5,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.10, lp2_engulfing_required=True,
            clp_min_bars=3, clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.30, atr_entry_threshold=0.80,
            enable_volume_filter=True, enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=1.5, max_stop_atr_pct=0.10, capital=100000.0, risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02, partial_tp_at_r=2.0, partial_tp_pct=0.50,
        ),
        intraday_config=IntradayLevelConfig(
            fractal_depth_m5=5, fractal_depth_h1=3, enable_h1=True,
            min_target_r=1.0, lookback_bars=1000,
        ),
        tier_config={
            'mode': '2tier_trail', 't1_pct': 0.30, 'min_rr': 1.5,
            'trail_factor': 0.7, 'trail_activation_r': 0.0,
        },
        name=name,
    )


# ──────────────────────────────────────────────────────────────────
# D1 Aggregation & Regime Indicators
# ──────────────────────────────────────────────────────────────────

def filter_rth(df):
    minutes = df['Datetime'].dt.hour * 60 + df['Datetime'].dt.minute
    mask = (minutes >= 14 * 60 + 30) & (minutes < 21 * 60)
    return df[mask].reset_index(drop=True)


def aggregate_to_daily(rth_df):
    rth_df = rth_df.copy()
    rth_df['Date'] = rth_df['Datetime'].dt.date
    daily = rth_df.groupby('Date').agg(
        Open=('Open', 'first'), High=('High', 'max'),
        Low=('Low', 'min'), Close=('Close', 'last'),
        Volume=('Volume', 'sum'),
    ).reset_index()
    daily['Date'] = pd.to_datetime(daily['Date'])
    return daily


def compute_atr(daily, period=14):
    high = daily['High'].values
    low = daily['Low'].values
    close = daily['Close'].values
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]

    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
    )
    atr = pd.Series(tr).rolling(window=period, min_periods=1).mean().values
    return atr


def compute_adx(daily, period=14):
    """Compute ADX(period) using Wilder's smoothing."""
    high = daily['High'].values.astype(float)
    low = daily['Low'].values.astype(float)
    close = daily['Close'].values.astype(float)
    n = len(high)

    # Directional movement
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]

        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0

        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )

    # Wilder's smoothing (EMA with alpha = 1/period)
    def wilder_smooth(arr, period):
        out = np.zeros(len(arr))
        out[period] = np.sum(arr[1:period + 1])
        for i in range(period + 1, len(arr)):
            out[i] = out[i - 1] - out[i - 1] / period + arr[i]
        return out

    smooth_tr = wilder_smooth(tr, period)
    smooth_plus_dm = wilder_smooth(plus_dm, period)
    smooth_minus_dm = wilder_smooth(minus_dm, period)

    # +DI, -DI
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

    # ADX = Wilder's smoothing of DX
    adx = np.zeros(n)
    start = 2 * period
    if start < n:
        adx[start] = np.mean(dx[period:start + 1])
        for i in range(start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx, plus_di, minus_di


def compute_regime_indicators(ticker):
    """Compute daily ADX, ATR, and ATR regime ratio for a ticker."""
    path = os.path.join(DATA_DIR, f'{ticker}_data.csv')
    df = pd.read_csv(path)
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    df = df.sort_values('Datetime').reset_index(drop=True)

    rth = filter_rth(df)
    daily = aggregate_to_daily(rth)

    # ATR(14)
    daily['ATR14'] = compute_atr(daily, 14)

    # ATR(50) for regime ratio
    daily['ATR50'] = compute_atr(daily, 50)

    # ATR regime ratio
    daily['ATR_ratio'] = daily['ATR14'] / daily['ATR50'].replace(0, np.nan)
    daily['ATR_ratio'] = daily['ATR_ratio'].fillna(1.0)

    # ADX(14)
    adx, plus_di, minus_di = compute_adx(daily, 14)
    daily['ADX'] = adx
    daily['Plus_DI'] = plus_di
    daily['Minus_DI'] = minus_di

    # Relative ATR
    daily['Rel_ATR'] = daily['ATR14'] / daily['Close']

    # Classify regime
    daily['Regime'] = 'NEUTRAL'
    favorable = (daily['ADX'] < 25) & (daily['ATR_ratio'] < 1.2) & (daily['ADX'] > 0)
    hostile = (daily['ADX'] > 30) | (daily['ATR_ratio'] > 1.5)
    daily.loc[favorable, 'Regime'] = 'FAVORABLE'
    daily.loc[hostile, 'Regime'] = 'HOSTILE'

    daily['Ticker'] = ticker
    return daily


# ──────────────────────────────────────────────────────────────────
# Trade Extraction
# ──────────────────────────────────────────────────────────────────

def run_and_get_trades(config, tickers, start_date, end_date):
    """Run backtest and return per-trade data with entry dates."""
    all_trades = []
    for ticker in tickers:
        m5_df = load_ticker_data(ticker)
        bt = Backtester(config)
        result = bt.run(m5_df, start_date=start_date, end_date=end_date)
        for trade in result.trades:
            all_trades.append({
                'ticker': trade.signal.ticker,
                'entry_time': trade.entry_time,
                'entry_date': trade.entry_time.normalize(),
                'exit_time': trade.exit_time,
                'direction': trade.direction.value,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'pnl': trade.pnl,
                'pnl_r': trade.pnl_r,
                'exit_reason': trade.exit_reason.value if trade.exit_reason else 'unknown',
                'is_winner': trade.pnl > 0,
                'position_size': trade.position_size,
            })
    return pd.DataFrame(all_trades) if all_trades else pd.DataFrame()


# ──────────────────────────────────────────────────────────────────
# Regime-Trade Correlation
# ──────────────────────────────────────────────────────────────────

def merge_trades_with_regime(trades_df, regime_df):
    """Join each trade with the regime on its entry date."""
    if trades_df.empty:
        return trades_df

    regime_lookup = regime_df[['Date', 'Ticker', 'ADX', 'ATR14', 'ATR_ratio',
                               'Rel_ATR', 'Regime']].copy()
    regime_lookup = regime_lookup.rename(columns={'Date': 'entry_date', 'Ticker': 'ticker'})

    merged = trades_df.merge(regime_lookup, on=['entry_date', 'ticker'], how='left')
    return merged


def compute_regime_stats(merged_df, group_col='Regime'):
    """Compute trade stats grouped by regime."""
    if merged_df.empty:
        return pd.DataFrame()

    stats = []
    for regime, grp in merged_df.groupby(group_col):
        n = len(grp)
        winners = grp['is_winner'].sum()
        pnl = grp['pnl'].sum()
        gross_profit = grp.loc[grp['pnl'] > 0, 'pnl'].sum()
        gross_loss = abs(grp.loc[grp['pnl'] <= 0, 'pnl'].sum())
        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        avg_r = grp['pnl_r'].mean()

        stats.append({
            'regime': regime,
            'trades': n,
            'winners': winners,
            'win_rate': winners / n if n > 0 else 0,
            'pf': pf,
            'total_pnl': pnl,
            'avg_r': avg_r,
            'avg_pnl': pnl / n if n > 0 else 0,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
        })

    return pd.DataFrame(stats)


def compute_adx_bucket_stats(merged_df):
    """Bucket trades by ADX ranges."""
    if merged_df.empty or 'ADX' not in merged_df.columns:
        return pd.DataFrame()

    merged = merged_df.dropna(subset=['ADX']).copy()
    merged['ADX_bucket'] = pd.cut(
        merged['ADX'],
        bins=[0, 15, 20, 25, 30, 40, 100],
        labels=['0-15', '15-20', '20-25', '25-30', '30-40', '40+']
    )
    return compute_regime_stats(merged, 'ADX_bucket')


def compute_atr_ratio_bucket_stats(merged_df):
    """Bucket trades by ATR regime ratio."""
    if merged_df.empty or 'ATR_ratio' not in merged_df.columns:
        return pd.DataFrame()

    merged = merged_df.dropna(subset=['ATR_ratio']).copy()
    merged['ATR_bucket'] = pd.cut(
        merged['ATR_ratio'],
        bins=[0, 0.8, 1.0, 1.2, 1.5, 10],
        labels=['<0.8', '0.8-1.0', '1.0-1.2', '1.2-1.5', '>1.5']
    )
    return compute_regime_stats(merged, 'ATR_bucket')


# ──────────────────────────────────────────────────────────────────
# Walk-Forward Window Regime Mapping
# ──────────────────────────────────────────────────────────────────

def map_wf_windows_to_regime(regime_df):
    """Map each WF window to its average ADX and ATR_ratio."""
    results = []
    for w in WF_WINDOWS:
        ts = pd.Timestamp(w['test_start'])
        te = pd.Timestamp(w['test_end'])
        window_regime = regime_df[
            (regime_df['Date'] >= ts) & (regime_df['Date'] < te)
        ]
        if window_regime.empty:
            results.append({**w, 'avg_adx': np.nan, 'avg_atr_ratio': np.nan,
                           'pct_favorable': 0, 'pct_hostile': 0, 'dominant': 'UNKNOWN'})
            continue

        avg_adx = window_regime['ADX'].mean()
        avg_atr_ratio = window_regime['ATR_ratio'].mean()
        regime_counts = window_regime['Regime'].value_counts(normalize=True)
        pct_favorable = regime_counts.get('FAVORABLE', 0) * 100
        pct_hostile = regime_counts.get('HOSTILE', 0) * 100

        dominant = regime_counts.idxmax() if not regime_counts.empty else 'UNKNOWN'

        results.append({
            **w,
            'avg_adx': avg_adx,
            'avg_atr_ratio': avg_atr_ratio,
            'pct_favorable': pct_favorable,
            'pct_hostile': pct_hostile,
            'dominant': dominant,
        })

    return pd.DataFrame(results)


# ──────────────────────────────────────────────────────────────────
# Report Generator
# ──────────────────────────────────────────────────────────────────

def generate_report(regime_dfs, trades_full, trades_is, trades_oos,
                    merged_full, merged_is, merged_oos,
                    regime_stats_full, adx_stats_full, atr_stats_full,
                    regime_stats_is, regime_stats_oos,
                    adx_stats_is, adx_stats_oos,
                    atr_stats_is, atr_stats_oos,
                    wf_regime_map, ticker_regime_summaries):

    lines = [
        "# Phase 5A — Regime Analysis",
        "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Tickers:** {', '.join(WHITELIST)}",
        f"**Config:** v4.1 best (trail_factor=0.7, t1_pct=0.30)",
        f"**Full period:** {FULL_START} to {FULL_END}",
        "",
        "---",
        "",
        "## 1. Regime Indicator Summary (per ticker)",
        "",
    ]

    for ticker, summary in ticker_regime_summaries.items():
        lines.extend([
            f"### {ticker}",
            "",
            f"| Metric | Full Period | IS ({IS_START}-{IS_END}) | OOS ({OOS_START}-{OOS_END}) |",
            f"|--------|-----------|-----|-----|",
            f"| Avg ADX(14) | {summary['full_adx']:.1f} | {summary['is_adx']:.1f} | {summary['oos_adx']:.1f} |",
            f"| Avg ATR(14) | ${summary['full_atr']:.2f} | ${summary['is_atr']:.2f} | ${summary['oos_atr']:.2f} |",
            f"| Avg ATR ratio | {summary['full_atr_ratio']:.2f} | {summary['is_atr_ratio']:.2f} | {summary['oos_atr_ratio']:.2f} |",
            f"| % FAVORABLE days | {summary['full_pct_fav']:.0f}% | {summary['is_pct_fav']:.0f}% | {summary['oos_pct_fav']:.0f}% |",
            f"| % HOSTILE days | {summary['full_pct_hos']:.0f}% | {summary['is_pct_hos']:.0f}% | {summary['oos_pct_hos']:.0f}% |",
            "",
        ])

    # 2. Trade-Regime Correlation (Full period)
    lines.extend([
        "---",
        "",
        "## 2. Trade Outcomes by Regime (Full Period)",
        "",
    ])

    if not regime_stats_full.empty:
        lines.append("### By Combined Regime")
        lines.append("")
        lines.append("| Regime | Trades | Win Rate | PF | Total P&L | Avg P&L | Avg R |")
        lines.append("|--------|--------|----------|-----|-----------|---------|-------|")
        for _, row in regime_stats_full.iterrows():
            lines.append(
                f"| {row['regime']} | {row['trades']:.0f} | {row['win_rate']*100:.1f}% | "
                f"{row['pf']:.2f} | ${row['total_pnl']:.0f} | ${row['avg_pnl']:.0f} | "
                f"{row['avg_r']:.2f} |"
            )
        lines.append("")

    if not adx_stats_full.empty:
        lines.append("### By ADX Bucket")
        lines.append("")
        lines.append("| ADX Range | Trades | Win Rate | PF | Total P&L | Avg P&L |")
        lines.append("|-----------|--------|----------|-----|-----------|---------|")
        for _, row in adx_stats_full.iterrows():
            lines.append(
                f"| {row['regime']} | {row['trades']:.0f} | {row['win_rate']*100:.1f}% | "
                f"{row['pf']:.2f} | ${row['total_pnl']:.0f} | ${row['avg_pnl']:.0f} |"
            )
        lines.append("")

    if not atr_stats_full.empty:
        lines.append("### By ATR Ratio Bucket")
        lines.append("")
        lines.append("| ATR Ratio | Trades | Win Rate | PF | Total P&L | Avg P&L |")
        lines.append("|-----------|--------|----------|-----|-----------|---------|")
        for _, row in atr_stats_full.iterrows():
            lines.append(
                f"| {row['regime']} | {row['trades']:.0f} | {row['win_rate']*100:.1f}% | "
                f"{row['pf']:.2f} | ${row['total_pnl']:.0f} | ${row['avg_pnl']:.0f} |"
            )
        lines.append("")

    # 3. IS vs OOS regime comparison
    lines.extend([
        "---",
        "",
        "## 3. IS vs OOS Regime Comparison",
        "",
        "### IS Period Trades by Regime",
        "",
    ])

    if not regime_stats_is.empty:
        lines.append("| Regime | Trades | Win Rate | PF | Total P&L |")
        lines.append("|--------|--------|----------|-----|-----------|")
        for _, row in regime_stats_is.iterrows():
            lines.append(
                f"| {row['regime']} | {row['trades']:.0f} | {row['win_rate']*100:.1f}% | "
                f"{row['pf']:.2f} | ${row['total_pnl']:.0f} |"
            )
        lines.append("")

    lines.append("### OOS Period Trades by Regime")
    lines.append("")

    if not regime_stats_oos.empty:
        lines.append("| Regime | Trades | Win Rate | PF | Total P&L |")
        lines.append("|--------|--------|----------|-----|-----------|")
        for _, row in regime_stats_oos.iterrows():
            lines.append(
                f"| {row['regime']} | {row['trades']:.0f} | {row['win_rate']*100:.1f}% | "
                f"{row['pf']:.2f} | ${row['total_pnl']:.0f} |"
            )
        lines.append("")

    # ADX buckets IS vs OOS
    for label, stats_df in [("IS", adx_stats_is), ("OOS", adx_stats_oos)]:
        if not stats_df.empty:
            lines.append(f"### {label} Trades by ADX Bucket")
            lines.append("")
            lines.append("| ADX Range | Trades | Win Rate | PF | Total P&L |")
            lines.append("|-----------|--------|----------|-----|-----------|")
            for _, row in stats_df.iterrows():
                lines.append(
                    f"| {row['regime']} | {row['trades']:.0f} | {row['win_rate']*100:.1f}% | "
                    f"{row['pf']:.2f} | ${row['total_pnl']:.0f} |"
                )
            lines.append("")

    # 4. Walk-Forward Window Regime Map
    lines.extend([
        "---",
        "",
        "## 4. Walk-Forward Windows Mapped to Regime",
        "",
        "| Window | Test Period | Avg ADX | Avg ATR Ratio | % Favorable | % Hostile | Dominant |",
        "|--------|-------------|---------|---------------|-------------|-----------|----------|",
    ])

    for _, row in wf_regime_map.iterrows():
        lines.append(
            f"| {row['id']} | {row['test_start']}->{row['test_end']} | "
            f"{row['avg_adx']:.1f} | {row['avg_atr_ratio']:.2f} | "
            f"{row['pct_favorable']:.0f}% | {row['pct_hostile']:.0f}% | "
            f"{row['dominant']} |"
        )

    # v4.1 WF results for cross-reference
    wf_pnls = {
        1: -1061, 2: -1880, 3: -990, 4: -1146,
        5: -1563, 6: -1045, 7: 526, 8: -833,
    }
    lines.extend([
        "",
        "### Cross-reference with v4.1 Walk-Forward P&L",
        "",
        "| Window | Test Period | P&L | Avg ADX | Avg ATR Ratio | Dominant Regime |",
        "|--------|-------------|------|---------|---------------|-----------------|",
    ])
    for _, row in wf_regime_map.iterrows():
        wid = int(row['id'])
        pnl = wf_pnls.get(wid, 0)
        status = "PROFIT" if pnl > 0 else "LOSS"
        lines.append(
            f"| {wid} | {row['test_start']}->{row['test_end']} | "
            f"${pnl} ({status}) | {row['avg_adx']:.1f} | "
            f"{row['avg_atr_ratio']:.2f} | {row['dominant']} |"
        )

    # 5. Verdict
    lines.extend([
        "",
        "---",
        "",
        "## 5. Verdict & Recommendations",
        "",
    ])

    # Analyze: is there a clear regime signal?
    if not regime_stats_full.empty:
        fav_row = regime_stats_full[regime_stats_full['regime'] == 'FAVORABLE']
        hos_row = regime_stats_full[regime_stats_full['regime'] == 'HOSTILE']
        neu_row = regime_stats_full[regime_stats_full['regime'] == 'NEUTRAL']

        fav_pf = fav_row['pf'].values[0] if len(fav_row) > 0 else 0
        hos_pf = hos_row['pf'].values[0] if len(hos_row) > 0 else 0
        fav_trades = int(fav_row['trades'].values[0]) if len(fav_row) > 0 else 0
        hos_trades = int(hos_row['trades'].values[0]) if len(hos_row) > 0 else 0

        lines.append(f"- **FAVORABLE regime:** {fav_trades} trades, PF={fav_pf:.2f}")
        lines.append(f"- **HOSTILE regime:** {hos_trades} trades, PF={hos_pf:.2f}")

        if fav_pf > 1.0 and hos_pf < 1.0 and fav_trades >= 10:
            lines.append("")
            lines.append("**CLEAR SIGNAL:** Strategy is profitable in FAVORABLE regime "
                         "and unprofitable in HOSTILE regime. Regime filter recommended.")
            lines.append("")
            lines.append("**Recommended filter:** Block trades when ADX > 25 OR ATR_ratio > 1.2")
        elif fav_pf > hos_pf and fav_trades >= 5:
            lines.append("")
            lines.append("**WEAK SIGNAL:** FAVORABLE regime has better PF but sample sizes "
                         "may be insufficient. Test regime filter with caution.")
        else:
            lines.append("")
            lines.append("**NO CLEAR SIGNAL:** Regime classification does not clearly separate "
                         "winning from losing trades. Regime filter may not help.")

    # ADX-specific finding
    if not adx_stats_full.empty:
        lines.append("")
        lines.append("### ADX-specific finding")
        for _, row in adx_stats_full.iterrows():
            status = "PROFITABLE" if row['pf'] > 1.0 else "UNPROFITABLE"
            lines.append(f"- ADX {row['regime']}: {int(row['trades'])} trades, "
                         f"PF={row['pf']:.2f} ({status})")

    lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("PHASE 5A — Regime Analysis")
    print(f"Tickers: {', '.join(WHITELIST)}")
    print("=" * 70)

    # Step 1: Compute regime indicators for all tickers
    print("\n1. Computing regime indicators (ADX, ATR) on D1 bars...")
    all_regime_dfs = {}
    combined_regime = []

    for ticker in WHITELIST:
        print(f"  {ticker}...")
        regime_df = compute_regime_indicators(ticker)
        all_regime_dfs[ticker] = regime_df
        combined_regime.append(regime_df)

    combined_regime_df = pd.concat(combined_regime, ignore_index=True)

    # Per-ticker regime summaries
    ticker_summaries = {}
    for ticker in WHITELIST:
        rdf = all_regime_dfs[ticker]
        is_mask = (rdf['Date'] >= pd.Timestamp(IS_START)) & (rdf['Date'] < pd.Timestamp(IS_END))
        oos_mask = (rdf['Date'] >= pd.Timestamp(OOS_START)) & (rdf['Date'] < pd.Timestamp(OOS_END))
        full_mask = rdf['ADX'] > 0  # skip warmup

        def pct_regime(df, regime):
            if len(df) == 0:
                return 0
            return (df['Regime'] == regime).sum() / len(df) * 100

        ticker_summaries[ticker] = {
            'full_adx': rdf.loc[full_mask, 'ADX'].mean(),
            'full_atr': rdf.loc[full_mask, 'ATR14'].mean(),
            'full_atr_ratio': rdf.loc[full_mask, 'ATR_ratio'].mean(),
            'full_pct_fav': pct_regime(rdf[full_mask], 'FAVORABLE'),
            'full_pct_hos': pct_regime(rdf[full_mask], 'HOSTILE'),
            'is_adx': rdf.loc[is_mask, 'ADX'].mean(),
            'is_atr': rdf.loc[is_mask, 'ATR14'].mean(),
            'is_atr_ratio': rdf.loc[is_mask, 'ATR_ratio'].mean(),
            'is_pct_fav': pct_regime(rdf[is_mask], 'FAVORABLE'),
            'is_pct_hos': pct_regime(rdf[is_mask], 'HOSTILE'),
            'oos_adx': rdf.loc[oos_mask, 'ADX'].mean(),
            'oos_atr': rdf.loc[oos_mask, 'ATR14'].mean(),
            'oos_atr_ratio': rdf.loc[oos_mask, 'ATR_ratio'].mean(),
            'oos_pct_fav': pct_regime(rdf[oos_mask], 'FAVORABLE'),
            'oos_pct_hos': pct_regime(rdf[oos_mask], 'HOSTILE'),
        }

        print(f"    ADX: IS={ticker_summaries[ticker]['is_adx']:.1f}, "
              f"OOS={ticker_summaries[ticker]['oos_adx']:.1f}")
        print(f"    ATR ratio: IS={ticker_summaries[ticker]['is_atr_ratio']:.2f}, "
              f"OOS={ticker_summaries[ticker]['oos_atr_ratio']:.2f}")
        print(f"    % Favorable: IS={ticker_summaries[ticker]['is_pct_fav']:.0f}%, "
              f"OOS={ticker_summaries[ticker]['oos_pct_fav']:.0f}%")

    # Step 2: Run v4.1 best config to get per-trade data
    print("\n2. Running v4.1 best config to get per-trade data...")
    config = make_v41_config()

    print("  Full period trades...")
    trades_full = run_and_get_trades(config, WHITELIST, FULL_START, FULL_END)
    print(f"    {len(trades_full)} trades total")

    print("  IS period trades...")
    trades_is = run_and_get_trades(config, WHITELIST, IS_START, IS_END)
    print(f"    {len(trades_is)} IS trades")

    print("  OOS period trades...")
    trades_oos = run_and_get_trades(config, WHITELIST, OOS_START, OOS_END)
    print(f"    {len(trades_oos)} OOS trades")

    # Step 3: Merge trades with regime
    print("\n3. Merging trades with regime data...")
    merged_full = merge_trades_with_regime(trades_full, combined_regime_df)
    merged_is = merge_trades_with_regime(trades_is, combined_regime_df)
    merged_oos = merge_trades_with_regime(trades_oos, combined_regime_df)

    # Step 4: Compute stats
    print("\n4. Computing regime-trade correlations...")

    regime_stats_full = compute_regime_stats(merged_full, 'Regime')
    adx_stats_full = compute_adx_bucket_stats(merged_full)
    atr_stats_full = compute_atr_ratio_bucket_stats(merged_full)

    regime_stats_is = compute_regime_stats(merged_is, 'Regime')
    regime_stats_oos = compute_regime_stats(merged_oos, 'Regime')
    adx_stats_is = compute_adx_bucket_stats(merged_is)
    adx_stats_oos = compute_adx_bucket_stats(merged_oos)
    atr_stats_is = compute_atr_ratio_bucket_stats(merged_is)
    atr_stats_oos = compute_atr_ratio_bucket_stats(merged_oos)

    # Print key findings
    print("\n  Full Period — Trades by Regime:")
    if not regime_stats_full.empty:
        for _, row in regime_stats_full.iterrows():
            print(f"    {row['regime']}: {int(row['trades'])} trades, "
                  f"WR={row['win_rate']*100:.1f}%, PF={row['pf']:.2f}, "
                  f"${row['total_pnl']:.0f}")

    print("\n  Full Period — Trades by ADX Bucket:")
    if not adx_stats_full.empty:
        for _, row in adx_stats_full.iterrows():
            print(f"    ADX {row['regime']}: {int(row['trades'])} trades, "
                  f"WR={row['win_rate']*100:.1f}%, PF={row['pf']:.2f}, "
                  f"${row['total_pnl']:.0f}")

    # Step 5: Map WF windows
    print("\n5. Mapping walk-forward windows to regime...")
    wf_regime_map = map_wf_windows_to_regime(combined_regime_df)
    for _, row in wf_regime_map.iterrows():
        print(f"    Window {int(row['id'])}: ADX={row['avg_adx']:.1f}, "
              f"ATR_ratio={row['avg_atr_ratio']:.2f}, "
              f"Dominant={row['dominant']}")

    # Step 6: Generate report
    print("\n6. Generating regime_analysis.md...")
    os.makedirs(RESULTS_DIR, exist_ok=True)

    report = generate_report(
        all_regime_dfs, trades_full, trades_is, trades_oos,
        merged_full, merged_is, merged_oos,
        regime_stats_full, adx_stats_full, atr_stats_full,
        regime_stats_is, regime_stats_oos,
        adx_stats_is, adx_stats_oos,
        atr_stats_is, atr_stats_oos,
        wf_regime_map, ticker_summaries,
    )

    report_path = os.path.join(RESULTS_DIR, 'regime_analysis.md')
    with open(report_path, 'w') as f:
        f.write(report)

    print(f"\n  Report written to: {report_path}")
    print("\n" + "=" * 70)
    print("PHASE 5A COMPLETE")
    print("=" * 70)


if __name__ == '__main__':
    main()
