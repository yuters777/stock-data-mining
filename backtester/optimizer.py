"""
Optimizer for the False Breakout Strategy Backtester.

Runs parameter experiments, walk-forward validation, and generates
comparison reports. Each experiment changes ONE parameter and measures
impact on IS and OOS performance.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from copy import deepcopy
from dataclasses import dataclass
from typing import Optional

from backtester.backtester import Backtester, BacktestConfig, BacktestResult
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig


@dataclass
class ExperimentResult:
    """Result of a single experiment variant."""
    exp_id: str
    title: str
    hypothesis: str
    change_desc: str
    param_name: str
    param_value: object
    is_results: dict  # {ticker: BacktestResult}
    oos_results: dict  # {ticker: BacktestResult}
    combined_is: dict  # aggregated metrics across tickers
    combined_oos: dict


def get_baseline_config() -> BacktestConfig:
    """Return the baseline v3.4 configuration."""
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=5,
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=5,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.20,
            lp2_engulfing_required=True,
            clp_min_bars=3,
            clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.30,
            atr_entry_threshold=0.75,
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=3.0,
            max_stop_atr_pct=0.15,
            capital=100000.0,
            risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02,
            partial_tp_at_r=2.0,
            partial_tp_pct=0.50,
        ),
        name="baseline_v3.4",
    )


def load_ticker_data(ticker: str) -> pd.DataFrame:
    """Load M5 data for a ticker."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    path = os.path.join(data_dir, f'{ticker}_data.csv')
    df = pd.read_csv(path)
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    df = df.sort_values(['Ticker', 'Datetime']).reset_index(drop=True)
    return df


def run_single_backtest(config: BacktestConfig, m5_df: pd.DataFrame,
                        start_date: str, end_date: str) -> BacktestResult:
    """Run a single backtest and return results."""
    bt = Backtester(config)
    result = bt.run(m5_df, start_date=start_date, end_date=end_date)
    result.performance['proximity_events'] = bt.proximity_events
    return result


def aggregate_metrics(results: dict) -> dict:
    """Aggregate metrics across multiple ticker results."""
    all_trades = []
    total_pnl = 0.0
    for ticker, result in results.items():
        all_trades.extend(result.trades)
        total_pnl += result.performance.get('total_pnl', 0.0)

    if not all_trades:
        return {
            'total_trades': 0, 'win_rate': 0.0, 'avg_r': 0.0,
            'profit_factor': 0.0, 'sharpe': 0.0, 'total_pnl': 0.0,
        }

    winners = [t for t in all_trades if t.pnl > 0]
    losers = [t for t in all_trades if t.pnl <= 0]
    gross_profit = sum(t.pnl for t in winners)
    gross_loss = abs(sum(t.pnl for t in losers))

    avg_sharpe = np.mean([
        r.performance.get('sharpe', 0.0) for r in results.values()
    ])

    return {
        'total_trades': len(all_trades),
        'win_rate': len(winners) / len(all_trades) if all_trades else 0.0,
        'avg_r': np.mean([t.pnl_r for t in all_trades]),
        'profit_factor': gross_profit / gross_loss if gross_loss > 0 else float('inf'),
        'sharpe': avg_sharpe,
        'total_pnl': total_pnl,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
    }


def run_experiment_variant(config: BacktestConfig, tickers: list,
                           is_start: str, is_end: str,
                           oos_start: str, oos_end: str) -> tuple[dict, dict, dict, dict]:
    """Run IS and OOS backtests for all tickers. Returns (is_results, oos_results, combined_is, combined_oos)."""
    is_results = {}
    oos_results = {}

    for ticker in tickers:
        m5_df = load_ticker_data(ticker)

        is_result = run_single_backtest(config, m5_df, is_start, is_end)
        is_results[ticker] = is_result

        oos_result = run_single_backtest(config, m5_df, oos_start, oos_end)
        oos_results[ticker] = oos_result

    combined_is = aggregate_metrics(is_results)
    combined_oos = aggregate_metrics(oos_results)

    return is_results, oos_results, combined_is, combined_oos


def format_experiment_log(exp_id: str, title: str, hypothesis: str,
                          change_desc: str, baseline_is: dict, baseline_oos: dict,
                          variants: list, best_variant: dict,
                          verdict: str, notes: str) -> str:
    """Format an experiment entry for the log."""
    lines = [
        f"## {exp_id}: {title}",
        f"**Hypothesis:** {hypothesis}",
        f"**Change:** {change_desc}",
        "",
        f"**Baseline (IS):** {baseline_is['win_rate']*100:.1f}% WR / "
        f"{baseline_is.get('sharpe', 0):.2f} Sharpe / "
        f"{baseline_is['total_trades']} trades / "
        f"PF={baseline_is['profit_factor']:.2f} / "
        f"${baseline_is['total_pnl']:.0f}",
        "",
        f"**Baseline (OOS):** {baseline_oos['win_rate']*100:.1f}% WR / "
        f"{baseline_oos.get('sharpe', 0):.2f} Sharpe / "
        f"{baseline_oos['total_trades']} trades / "
        f"PF={baseline_oos['profit_factor']:.2f} / "
        f"${baseline_oos['total_pnl']:.0f}",
        "",
        "### Variants Tested",
        "",
        "| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |",
        "|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|",
    ]

    for v in variants:
        vis = v['combined_is']
        voos = v['combined_oos']
        lines.append(
            f"| {v['label']} | {vis['total_trades']} | "
            f"{vis['win_rate']*100:.1f}% | {vis['profit_factor']:.2f} | "
            f"${vis['total_pnl']:.0f} | {voos['total_trades']} | "
            f"{voos['win_rate']*100:.1f}% | {voos['profit_factor']:.2f} | "
            f"${voos['total_pnl']:.0f} |"
        )

    if best_variant:
        bis = best_variant['combined_is']
        boos = best_variant['combined_oos']
        lines.extend([
            "",
            f"**Best Variant (IS):** {best_variant['label']} — "
            f"{bis['win_rate']*100:.1f}% WR / {bis.get('sharpe', 0):.2f} Sharpe / "
            f"{bis['total_trades']} trades / PF={bis['profit_factor']:.2f} / "
            f"${bis['total_pnl']:.0f}",
            f"**Best Variant (OOS):** {boos['win_rate']*100:.1f}% WR / "
            f"{boos.get('sharpe', 0):.2f} Sharpe / "
            f"{boos['total_trades']} trades / PF={boos['profit_factor']:.2f} / "
            f"${boos['total_pnl']:.0f}",
        ])

    lines.extend([
        "",
        f"**Verdict:** {verdict}",
        f"**Notes:** {notes}",
        "",
        "---",
        "",
    ])

    return "\n".join(lines)


def pick_best_variant(variants: list, baseline_is: dict) -> tuple[dict, str]:
    """Pick best variant based on IS profit factor, then validate on OOS.
    Returns (best_variant, verdict).
    """
    if not variants:
        return None, "REJECT"

    # Sort by IS profit factor (primary), then total P&L (secondary)
    scored = []
    for v in variants:
        pf = v['combined_is']['profit_factor']
        pnl = v['combined_is']['total_pnl']
        trades = v['combined_is']['total_trades']
        # Need minimum trades for significance
        if trades < 5:
            score = -999
        else:
            score = pf * 100 + pnl / 100
        scored.append((score, v))

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][1]

    # Compare to baseline
    baseline_pf = baseline_is['profit_factor']
    best_pf = best['combined_is']['profit_factor']
    best_oos_pf = best['combined_oos']['profit_factor']
    best_oos_trades = best['combined_oos']['total_trades']

    if best_pf <= baseline_pf and best['combined_is']['total_pnl'] <= baseline_is['total_pnl']:
        verdict = "REJECT"
    elif best_oos_trades < 3:
        verdict = "INCONCLUSIVE"
    elif best_oos_pf > baseline_pf * 0.8:  # OOS within 80% of IS improvement
        verdict = "ACCEPT"
    else:
        verdict = "INCONCLUSIVE"

    return best, verdict


class WalkForwardValidator:
    """Rolling walk-forward validation."""

    def __init__(self, config: BacktestConfig, tickers: list,
                 train_months: int = 3, test_months: int = 1):
        self.config = config
        self.tickers = tickers
        self.train_months = train_months
        self.test_months = test_months

    def run(self, overall_start: str = '2025-02-10',
            overall_end: str = '2026-01-31') -> list[dict]:
        """Run walk-forward windows. Returns list of window results."""
        start = pd.Timestamp(overall_start)
        end = pd.Timestamp(overall_end)

        windows = []
        current = start

        while True:
            train_end = current + pd.DateOffset(months=self.train_months)
            test_end = train_end + pd.DateOffset(months=self.test_months)

            if test_end > end:
                break

            windows.append({
                'train_start': current.strftime('%Y-%m-%d'),
                'train_end': train_end.strftime('%Y-%m-%d'),
                'test_start': train_end.strftime('%Y-%m-%d'),
                'test_end': test_end.strftime('%Y-%m-%d'),
            })

            current += pd.DateOffset(months=self.test_months)

        results = []
        for i, w in enumerate(windows):
            print(f"  Walk-forward window {i+1}/{len(windows)}: "
                  f"Train {w['train_start']}→{w['train_end']}, "
                  f"Test {w['test_start']}→{w['test_end']}")

            window_results = {}
            for ticker in self.tickers:
                m5_df = load_ticker_data(ticker)
                oos_result = run_single_backtest(
                    self.config, m5_df, w['test_start'], w['test_end']
                )
                window_results[ticker] = oos_result

            combined = aggregate_metrics(window_results)
            combined['window'] = i + 1
            combined['test_start'] = w['test_start']
            combined['test_end'] = w['test_end']
            results.append(combined)

        return results

    @staticmethod
    def summarize(results: list) -> dict:
        """Summarize walk-forward results."""
        sharpes = [r.get('sharpe', 0) for r in results]
        pfs = [r['profit_factor'] for r in results]
        wrs = [r['win_rate'] for r in results]
        trades = [r['total_trades'] for r in results]
        pnls = [r['total_pnl'] for r in results]

        positive_sharpe = sum(1 for s in sharpes if s > 0)

        return {
            'n_windows': len(results),
            'mean_sharpe': np.mean(sharpes) if sharpes else 0,
            'std_sharpe': np.std(sharpes) if sharpes else 0,
            'worst_sharpe': min(sharpes) if sharpes else 0,
            'best_sharpe': max(sharpes) if sharpes else 0,
            'positive_sharpe_windows': positive_sharpe,
            'mean_pf': np.mean(pfs) if pfs else 0,
            'mean_wr': np.mean(wrs) if wrs else 0,
            'total_trades': sum(trades),
            'mean_trades_per_window': np.mean(trades) if trades else 0,
            'total_pnl': sum(pnls),
            'mean_pnl_per_window': np.mean(pnls) if pnls else 0,
            'window_results': results,
        }
