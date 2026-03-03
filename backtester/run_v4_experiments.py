"""
v4 Experiments — Universe Expansion & Volatility Profiles

Phase 4A: Data preparation + volatility classification
EXP-V001: Uniform v3 winner config on all 7 tickers (baseline per ticker)
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
from backtester.optimizer import (
    load_ticker_data, run_single_backtest, aggregate_metrics,
)

# ──────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────

TICKERS = ['AAPL', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA', 'TSLA']
IS_START = '2025-02-10'
IS_END = '2025-10-01'
OOS_START = '2025-10-01'
OOS_END = '2026-01-31'

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
EXP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'experiments')
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')


# ──────────────────────────────────────────────────────────────────
# Phase 4A: Data Preparation & Volatility Classification
# ──────────────────────────────────────────────────────────────────

def filter_rth(df):
    """Filter to regular trading hours (14:30-21:00 UTC = 9:30-16:00 ET)."""
    minutes = df['Datetime'].dt.hour * 60 + df['Datetime'].dt.minute
    mask = (minutes >= 14 * 60 + 30) & (minutes < 21 * 60)
    return df[mask].reset_index(drop=True)


def aggregate_to_daily(rth_df):
    """Aggregate RTH M5 bars to daily OHLCV."""
    rth_df = rth_df.copy()
    rth_df['Date'] = rth_df['Datetime'].dt.date
    daily = rth_df.groupby('Date').agg(
        Open=('Open', 'first'),
        High=('High', 'max'),
        Low=('Low', 'min'),
        Close=('Close', 'last'),
        Volume=('Volume', 'sum'),
    ).reset_index()
    daily['Date'] = pd.to_datetime(daily['Date'])
    return daily


def compute_atr(daily, period=14):
    """Compute ATR on daily data."""
    high = daily['High']
    low = daily['Low']
    close = daily['Close']
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(window=period, min_periods=1).mean()
    return atr


def classify_volatility(avg_rel_atr):
    """Classify ticker into volatility bucket."""
    if avg_rel_atr >= 0.030:
        return 'HIGH_VOL'
    else:
        return 'MED_VOL'


def prepare_all_tickers():
    """Load, validate, and classify all tickers. Returns summary dict."""
    print("=" * 70)
    print("PHASE 4A: Data Preparation & Volatility Classification")
    print("=" * 70)

    summaries = {}

    for ticker in TICKERS:
        path = os.path.join(DATA_DIR, f'{ticker}_data.csv')
        assert os.path.exists(path), f"Missing data file: {path}"

        df = pd.read_csv(path)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)

        # Filter RTH
        rth = filter_rth(df)
        assert len(rth) > 0, f"No RTH bars for {ticker}"

        # Aggregate to daily
        daily = aggregate_to_daily(rth)

        # Compute ATR
        atr = compute_atr(daily)
        daily['ATR'] = atr
        daily['Rel_ATR'] = daily['ATR'] / daily['Close']

        avg_price = daily['Close'].mean()
        avg_atr = daily['ATR'].mean()
        avg_rel_atr = daily['Rel_ATR'].mean()
        bucket = classify_volatility(avg_rel_atr)

        date_min = rth['Datetime'].min().strftime('%Y-%m-%d')
        date_max = rth['Datetime'].max().strftime('%Y-%m-%d')

        # Check OOS coverage
        oos_rth = rth[rth['Datetime'] >= pd.Timestamp(OOS_START)]
        oos_days = oos_rth['Datetime'].dt.date.nunique()

        summaries[ticker] = {
            'ticker': ticker,
            'total_bars': len(rth),
            'date_min': date_min,
            'date_max': date_max,
            'avg_price': avg_price,
            'avg_atr': avg_atr,
            'avg_rel_atr': avg_rel_atr,
            'bucket': bucket,
            'oos_days': oos_days,
        }

    # Print summary table
    print()
    print(f"{'Ticker':<8} {'Bars':>7} {'Date Range':<27} {'Avg Price':>10} "
          f"{'Avg ATR':>8} {'Rel ATR':>8} {'Bucket':<10} {'OOS Days':>9}")
    print("-" * 100)
    for s in summaries.values():
        print(f"{s['ticker']:<8} {s['total_bars']:>7} {s['date_min']} to {s['date_max']}  "
              f"${s['avg_price']:>8.2f} ${s['avg_atr']:>6.2f} "
              f"{s['avg_rel_atr']:>7.4f} {s['bucket']:<10} {s['oos_days']:>9}")

    # Summary counts
    med = [s for s in summaries.values() if s['bucket'] == 'MED_VOL']
    high = [s for s in summaries.values() if s['bucket'] == 'HIGH_VOL']
    print(f"\nMED_VOL ({len(med)}): {', '.join(s['ticker'] for s in med)}")
    print(f"HIGH_VOL ({len(high)}): {', '.join(s['ticker'] for s in high)}")

    # Warn about limited data
    for s in summaries.values():
        if s['oos_days'] < 60:
            print(f"  WARNING: {s['ticker']} has only {s['oos_days']} OOS trading days "
                  f"(data ends {s['date_max']})")

    return summaries


# ──────────────────────────────────────────────────────────────────
# V3 Winner Config (STRUCT-002d)
# ──────────────────────────────────────────────────────────────────

def get_v3_winner_config(name='v3_winner') -> BacktestConfig:
    """Return the v3 winning configuration (STRUCT-002d: 2-tier trail)."""
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=10,
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=5,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.10,
            lp2_engulfing_required=True,
            clp_min_bars=3,
            clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.30,
            atr_entry_threshold=0.80,
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=1.5,
            max_stop_atr_pct=0.10,
            capital=100000.0,
            risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02,
            partial_tp_at_r=2.0,
            partial_tp_pct=0.50,
        ),
        intraday_config=IntradayLevelConfig(
            fractal_depth_m5=5,
            fractal_depth_h1=3,
            enable_h1=True,
            min_target_r=1.0,
            lookback_bars=1000,
        ),
        tier_config={'mode': '2tier_trail', 't1_pct': 0.50, 'min_rr': 1.5},
        name=name,
    )


# ──────────────────────────────────────────────────────────────────
# EXP-V001: Uniform Config on All 7 Tickers
# ──────────────────────────────────────────────────────────────────

def count_exits(trades):
    """Count exit types."""
    counts = {'target': 0, 'stop': 0, 'eod': 0, 'breakeven': 0, 'other': 0}
    for t in trades:
        if t.exit_reason == ExitReason.TARGET_HIT:
            counts['target'] += 1
        elif t.exit_reason == ExitReason.STOP_LOSS:
            counts['stop'] += 1
        elif t.exit_reason == ExitReason.EOD_EXIT:
            counts['eod'] += 1
        elif t.exit_reason == ExitReason.BREAKEVEN:
            counts['breakeven'] += 1
        else:
            counts['other'] += 1
    return counts


def run_exp_v001(vol_summaries):
    """Run EXP-V001: uniform v3 winner on all 7 tickers."""
    print("\n" + "=" * 70)
    print("EXP-V001: Uniform Config (v3 Winner) on All 7 Tickers")
    print("=" * 70)

    config = get_v3_winner_config(name='EXP-V001')

    is_results = {}
    oos_results = {}
    is_per_ticker = {}
    oos_per_ticker = {}

    for ticker in TICKERS:
        print(f"\n  Running {ticker} ({vol_summaries[ticker]['bucket']})...")
        m5_df = load_ticker_data(ticker)

        # IS
        bt_is = Backtester(config)
        is_result = bt_is.run(m5_df, start_date=IS_START, end_date=IS_END)
        is_result.performance['proximity_events'] = bt_is.proximity_events
        is_result.performance['intraday_targets_found'] = bt_is.intraday_targets_found
        is_result.performance['intraday_targets_used'] = bt_is.intraday_targets_used
        is_results[ticker] = is_result

        # OOS
        bt_oos = Backtester(config)
        oos_result = bt_oos.run(m5_df, start_date=OOS_START, end_date=OOS_END)
        oos_result.performance['proximity_events'] = bt_oos.proximity_events
        oos_result.performance['intraday_targets_found'] = bt_oos.intraday_targets_found
        oos_result.performance['intraday_targets_used'] = bt_oos.intraday_targets_used
        oos_results[ticker] = oos_result

        # Per-ticker summary
        is_perf = is_result.performance
        oos_perf = oos_result.performance
        is_exits = count_exits(is_result.trades)
        oos_exits = count_exits(oos_result.trades)

        is_per_ticker[ticker] = {
            **is_perf,
            'exits': is_exits,
            'bucket': vol_summaries[ticker]['bucket'],
        }
        oos_per_ticker[ticker] = {
            **oos_perf,
            'exits': oos_exits,
            'bucket': vol_summaries[ticker]['bucket'],
        }

        # Print inline
        is_t = is_perf.get('total_trades', 0)
        is_wr = is_perf.get('win_rate', 0) * 100
        is_pf = is_perf.get('profit_factor', 0)
        is_pnl = is_perf.get('total_pnl', 0)
        oos_t = oos_perf.get('total_trades', 0)
        oos_wr = oos_perf.get('win_rate', 0) * 100
        oos_pf = oos_perf.get('profit_factor', 0)
        oos_pnl = oos_perf.get('total_pnl', 0)

        print(f"    IS:  {is_t} trades, {is_wr:.1f}% WR, PF={is_pf:.2f}, ${is_pnl:.0f}")
        print(f"    OOS: {oos_t} trades, {oos_wr:.1f}% WR, PF={oos_pf:.2f}, ${oos_pnl:.0f}")
        print(f"    OOS exits: target={oos_exits['target']} stop={oos_exits['stop']} "
              f"eod={oos_exits['eod']} trail/be={oos_exits['breakeven']}")

    # Aggregate
    combined_is = aggregate_metrics(is_results)
    combined_oos = aggregate_metrics(oos_results)

    # By bucket
    med_oos = {t: r for t, r in oos_results.items() if vol_summaries[t]['bucket'] == 'MED_VOL'}
    high_oos = {t: r for t, r in oos_results.items() if vol_summaries[t]['bucket'] == 'HIGH_VOL'}
    med_combined = aggregate_metrics(med_oos) if med_oos else {}
    high_combined = aggregate_metrics(high_oos) if high_oos else {}

    # Print summary
    print("\n" + "-" * 70)
    print("EXP-V001 SUMMARY")
    print("-" * 70)
    print(f"\nPortfolio IS:  {combined_is['total_trades']} trades, "
          f"{combined_is['win_rate']*100:.1f}% WR, "
          f"PF={combined_is['profit_factor']:.2f}, "
          f"${combined_is['total_pnl']:.0f}")
    print(f"Portfolio OOS: {combined_oos['total_trades']} trades, "
          f"{combined_oos['win_rate']*100:.1f}% WR, "
          f"PF={combined_oos['profit_factor']:.2f}, "
          f"${combined_oos['total_pnl']:.0f}")

    if med_combined:
        print(f"\nMED_VOL OOS:  {med_combined['total_trades']} trades, "
              f"{med_combined['win_rate']*100:.1f}% WR, "
              f"PF={med_combined['profit_factor']:.2f}, "
              f"${med_combined['total_pnl']:.0f}")
    if high_combined:
        print(f"HIGH_VOL OOS: {high_combined['total_trades']} trades, "
              f"{high_combined['win_rate']*100:.1f}% WR, "
              f"PF={high_combined['profit_factor']:.2f}, "
              f"${high_combined['total_pnl']:.0f}")

    # Per-ticker OOS ranking
    print("\nPer-Ticker OOS Ranking (by PF):")
    ranked = sorted(oos_per_ticker.items(), key=lambda x: x[1].get('profit_factor', 0), reverse=True)
    for ticker, perf in ranked:
        t = perf.get('total_trades', 0)
        wr = perf.get('win_rate', 0) * 100
        pf = perf.get('profit_factor', 0)
        pnl = perf.get('total_pnl', 0)
        bucket = perf['bucket']
        print(f"  {ticker:<6} ({bucket:<8}): {t:>3} trades, "
              f"{wr:>5.1f}% WR, PF={pf:.2f}, ${pnl:>+8.0f}")

    return {
        'is_results': is_results,
        'oos_results': oos_results,
        'is_per_ticker': is_per_ticker,
        'oos_per_ticker': oos_per_ticker,
        'combined_is': combined_is,
        'combined_oos': combined_oos,
        'med_combined': med_combined,
        'high_combined': high_combined,
    }


# ──────────────────────────────────────────────────────────────────
# Experiment Log Writer
# ──────────────────────────────────────────────────────────────────

def write_experiment_log(vol_summaries, v001_results):
    """Write experiment log to experiments/EXPERIMENT_LOG_v4.md"""
    os.makedirs(EXP_DIR, exist_ok=True)

    lines = [
        "# Experiment Log v4 — Universe Expansion & Volatility Profiles",
        "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Tickers:** {', '.join(TICKERS)}",
        f"**IS Period:** {IS_START} to {IS_END}",
        f"**OOS Period:** {OOS_START} to {OOS_END}",
        f"**Baseline Config:** v3 winner (STRUCT-002d: 2-tier trail, H1 k=3, min_rr=1.5)",
        "",
        "---",
        "",
        "## Phase 4A: Data Summary",
        "",
        f"| Ticker | Bars | Date Range | Avg Price | Avg ATR | Rel ATR | Bucket | OOS Days |",
        f"|--------|------|------------|-----------|---------|---------|--------|----------|",
    ]

    for s in vol_summaries.values():
        lines.append(
            f"| {s['ticker']} | {s['total_bars']} | "
            f"{s['date_min']} to {s['date_max']} | "
            f"${s['avg_price']:.2f} | ${s['avg_atr']:.2f} | "
            f"{s['avg_rel_atr']:.4f} | {s['bucket']} | {s['oos_days']} |"
        )

    lines.extend(["", "---", ""])

    # EXP-V001
    ci = v001_results['combined_is']
    co = v001_results['combined_oos']
    mc = v001_results.get('med_combined', {})
    hc = v001_results.get('high_combined', {})

    lines.extend([
        "## EXP-V001: Uniform Config (v3 Winner) on All 7 Tickers",
        "",
        "**Hypothesis:** The v3 winner config (STRUCT-002d) will be naturally profitable "
        "on MED_VOL tickers and struggle on HIGH_VOL tickers, due to stop sizing and "
        "level reliability differences.",
        "",
        "**Config:** fractal_depth=10, atr_entry=0.80, max_stop_atr=0.10, tail=0.10, "
        "min_rr=1.5, 2-tier trail (50% H1 + trail), H1 fractal k=3",
        "",
        "### Per-Ticker Results",
        "",
        "| Ticker | Bucket | IS Trades | IS WR | IS PF | IS P&L | "
        "OOS Trades | OOS WR | OOS PF | OOS P&L |",
        "|--------|--------|-----------|-------|-------|--------|"
        "------------|--------|--------|---------|",
    ])

    for ticker in TICKERS:
        ip = v001_results['is_per_ticker'][ticker]
        op = v001_results['oos_per_ticker'][ticker]
        bucket = vol_summaries[ticker]['bucket']
        lines.append(
            f"| {ticker} | {bucket} | "
            f"{ip.get('total_trades', 0)} | {ip.get('win_rate', 0)*100:.1f}% | "
            f"{ip.get('profit_factor', 0):.2f} | ${ip.get('total_pnl', 0):.0f} | "
            f"{op.get('total_trades', 0)} | {op.get('win_rate', 0)*100:.1f}% | "
            f"{op.get('profit_factor', 0):.2f} | ${op.get('total_pnl', 0):.0f} |"
        )

    lines.extend(["", "### OOS Exit Analysis", ""])
    lines.append("| Ticker | Bucket | Target | Stop | EOD | Trail/BE | Total |")
    lines.append("|--------|--------|--------|------|-----|----------|-------|")

    for ticker in TICKERS:
        op = v001_results['oos_per_ticker'][ticker]
        ex = op.get('exits', {})
        total = sum(ex.values())
        bucket = vol_summaries[ticker]['bucket']
        lines.append(
            f"| {ticker} | {bucket} | "
            f"{ex.get('target', 0)} | {ex.get('stop', 0)} | "
            f"{ex.get('eod', 0)} | {ex.get('breakeven', 0)} | {total} |"
        )

    # Portfolio summary
    lines.extend([
        "",
        "### Portfolio Summary",
        "",
        "| Segment | OOS Trades | OOS WR | OOS PF | OOS P&L |",
        "|---------|------------|--------|--------|---------|",
        f"| Portfolio | {co['total_trades']} | {co['win_rate']*100:.1f}% | "
        f"{co['profit_factor']:.2f} | ${co['total_pnl']:.0f} |",
    ])
    if mc:
        lines.append(
            f"| MED_VOL | {mc['total_trades']} | {mc['win_rate']*100:.1f}% | "
            f"{mc['profit_factor']:.2f} | ${mc['total_pnl']:.0f} |"
        )
    if hc:
        lines.append(
            f"| HIGH_VOL | {hc['total_trades']} | {hc['win_rate']*100:.1f}% | "
            f"{hc['profit_factor']:.2f} | ${hc['total_pnl']:.0f} |"
        )

    # Signal funnel per ticker
    lines.extend(["", "### Per-Ticker Signal Funnels (OOS)", ""])
    for ticker in TICKERS:
        result = v001_results['oos_results'][ticker]
        perf = result.performance
        bucket = vol_summaries[ticker]['bucket']
        exits = v001_results['oos_per_ticker'][ticker].get('exits', {})
        total_trades = perf.get('total_trades', 0)

        lines.extend([
            f"```",
            f"SIGNAL FUNNEL — {ticker} ({bucket}) — EXP-V001 (OOS)",
            f"{'=' * 50}",
            f"D1 levels detected:     {result.level_stats.get('total_levels', 0)}",
            f"  Confirmed (BPU):      {result.level_stats.get('confirmed_bpu', 0)}",
            f"  Mirror:               {result.level_stats.get('mirrors', 0)}",
            f"  Invalidated:          {result.level_stats.get('invalidated_sawing', 0)}",
            f"",
            f"Trades executed:        {total_trades}",
            f"  Target exits:         {exits.get('target', 0)}",
            f"  Stop exits:           {exits.get('stop', 0)}",
            f"  EOD exits:            {exits.get('eod', 0)}",
            f"  Trail/breakeven:      {exits.get('breakeven', 0)}",
            f"",
            f"Win rate:               {perf.get('win_rate', 0)*100:.1f}%",
            f"Profit factor:          {perf.get('profit_factor', 0):.2f}",
            f"Total P&L:              ${perf.get('total_pnl', 0):.0f}",
            f"Max drawdown:           {perf.get('max_drawdown_pct', 0):.2f}%",
            f"Sharpe:                 {perf.get('sharpe', 0):.2f}",
            f"Intraday targets used:  {perf.get('intraday_targets_used', 0)}",
            f"```",
            f"",
        ])

    # Verdict
    profitable_oos = sum(
        1 for t in TICKERS
        if v001_results['oos_per_ticker'][t].get('total_pnl', 0) > 0
    )
    med_profitable = sum(
        1 for t in TICKERS
        if vol_summaries[t]['bucket'] == 'MED_VOL'
        and v001_results['oos_per_ticker'][t].get('total_pnl', 0) > 0
    )
    med_total = sum(1 for s in vol_summaries.values() if s['bucket'] == 'MED_VOL')
    high_total = sum(1 for s in vol_summaries.values() if s['bucket'] == 'HIGH_VOL')

    lines.extend([
        "---",
        "",
        "## EXP-V001 Verdict",
        "",
        f"- **Profitable tickers (OOS):** {profitable_oos}/{len(TICKERS)}",
        f"- **MED_VOL profitable:** {med_profitable}/{med_total}",
        f"- **Portfolio PF:** {co['profit_factor']:.2f}",
        f"- **Portfolio P&L:** ${co['total_pnl']:.0f}",
        f"- **Total OOS trades:** {co['total_trades']}",
        "",
    ])

    if co['profit_factor'] > 1.0 and co['total_trades'] >= 20:
        lines.append("**Verdict: PROMISING** — Strategy shows positive edge across expanded universe.")
    elif co['total_trades'] < 10:
        lines.append("**Verdict: INCONCLUSIVE** — Too few trades for reliable assessment.")
    else:
        lines.append("**Verdict: NEEDS WORK** — Uniform config does not achieve portfolio profitability.")

    lines.extend([
        "",
        "**Next steps:**",
        "- EXP-V002: Test adaptive volatility profiles (different params per bucket)",
        "- Focus on HIGH_VOL parameter adjustments if MED_VOL is naturally profitable",
        "",
    ])

    log_path = os.path.join(EXP_DIR, 'EXPERIMENT_LOG_v4.md')
    with open(log_path, 'w') as f:
        f.write("\n".join(lines))

    print(f"\nExperiment log written to: {log_path}")
    return log_path


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("V4 EXPERIMENTS — Universe Expansion & Volatility Profiles")
    print(f"Tickers: {', '.join(TICKERS)}")
    print(f"IS: {IS_START} to {IS_END} | OOS: {OOS_START} to {OOS_END}")
    print("=" * 70)

    # Phase 4A: Data preparation
    vol_summaries = prepare_all_tickers()

    # EXP-V001: Uniform config
    v001_results = run_exp_v001(vol_summaries)

    # Write experiment log
    write_experiment_log(vol_summaries, v001_results)

    # Final summary
    print("\n" + "=" * 70)
    print("V4 PHASE 4A + EXP-V001 COMPLETE")
    print("=" * 70)
    co = v001_results['combined_oos']
    print(f"Portfolio OOS: {co['total_trades']} trades, "
          f"{co['win_rate']*100:.1f}% WR, "
          f"PF={co['profit_factor']:.2f}, "
          f"${co['total_pnl']:.0f}")
    print("\nDone!")


if __name__ == '__main__':
    main()
