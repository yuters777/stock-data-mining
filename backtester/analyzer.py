"""
Analyzer for the False Breakout Strategy Backtester.

Generates signal funnel reports, performance metrics, regime analysis,
and comparison tables between backtest runs.
"""

import numpy as np
from backtester.backtester import BacktestResult
from backtester.core.trade_manager import ExitReason


class Analyzer:

    @staticmethod
    def signal_funnel_report(result: BacktestResult) -> str:
        """Generate the signal funnel report string."""
        funnel = result.funnel_entries
        level_stats = result.level_stats

        total_signals = len(funnel)
        passed = sum(1 for e in funnel if not e.blocked_by)

        blocked_counts = {}
        for e in funnel:
            if e.blocked_by:
                key = e.blocked_by
                if 'HARD BLOCK' in e.blocked_reason:
                    key = 'atr_hard_block'
                elif 'below entry' in e.blocked_reason:
                    key = 'atr_threshold'
                blocked_counts[key] = blocked_counts.get(key, 0) + 1

        trades = result.trades
        winners = sum(1 for t in trades if t.is_winner)
        losers = sum(1 for t in trades if not t.is_winner)
        eod_exits = sum(1 for t in trades if t.exit_reason == ExitReason.EOD_EXIT)

        report = f"""
SIGNAL FUNNEL — {result.config_name} — {result.ticker}
{'═' * 50}
Total D1 levels generated:                  {level_stats.get('total_levels', 0)}
  Confirmed (≥1 BPU):                       {level_stats.get('confirmed_bpu', 0)}
  Mirror confirmed:                         {level_stats.get('mirrors', 0)}
  Invalidated (sawing):                     {level_stats.get('invalidated_sawing', 0)}

Total M5 level proximity events:            {result.performance.get('proximity_events', 'N/A')}
  └─ Pattern formed (LP1/LP2/CLP):         {total_signals}
     ├─ Blocked by ATR < 0.30:             {blocked_counts.get('atr_hard_block', 0)}
     ├─ Blocked by ATR < threshold:        {blocked_counts.get('atr_threshold', 0)}
     ├─ Blocked by stop too big:           {blocked_counts.get('risk_stop', 0)}
     ├─ Blocked by R:R < minimum:          {blocked_counts.get('risk_rr', 0)}
     ├─ Blocked by time filter:            {blocked_counts.get('time', 0)}
     ├─ Blocked by volume (true BO):       {blocked_counts.get('volume', 0)}
     ├─ Blocked by squeeze:                {blocked_counts.get('squeeze', 0)}
     ├─ Blocked by earnings:               {blocked_counts.get('earnings', 0)}
     ├─ Blocked by open position:          {blocked_counts.get('position_limit', 0)}
     └─ ✅ VALID SIGNALS:                   {passed}
        ├─ Winners:                         {winners}
        ├─ Losers:                          {losers}
        └─ EOD exits:                       {eod_exits}
"""
        return report.strip()

    @staticmethod
    def performance_report(result: BacktestResult) -> str:
        """Generate performance metrics report."""
        p = result.performance
        if p.get('total_trades', 0) == 0:
            return f"No trades for {result.config_name} — {result.ticker}"

        report = f"""
PERFORMANCE — {result.config_name} — {result.ticker}
{'═' * 50}
Total Trades:      {p['total_trades']}
Winners:           {p['winners']}  ({p['win_rate']*100:.1f}%)
Losers:            {p['losers']}
EOD Exits:         {p.get('eod_exits', 0)}

Avg R-Multiple:    {p['avg_r']:.2f}R
Profit Factor:     {p['profit_factor']:.2f}
Sharpe Ratio:      {p.get('sharpe', 0):.2f}

Total P&L:         ${p['total_pnl']:.2f}
Gross Profit:      ${p['gross_profit']:.2f}
Gross Loss:        ${p['gross_loss']:.2f}
Net Return:        {p.get('net_return_pct', 0):.2f}%

Max Drawdown:      {p.get('max_drawdown_pct', 0):.2f}%
Equity Start:      ${p.get('equity_start', 0):,.2f}
Equity Final:      ${p.get('equity_final', 0):,.2f}

Avg Winner:        ${p.get('avg_winner', 0):.2f}
Avg Loser:         ${p.get('avg_loser', 0):.2f}
Max Winner:        ${p.get('max_winner', 0):.2f}
Max Loser:         ${p.get('max_loser', 0):.2f}
"""
        return report.strip()

    @staticmethod
    def level_audit_report(result: BacktestResult) -> str:
        """Generate level detection audit."""
        ls = result.level_stats
        report = f"""
LEVEL AUDIT — {result.config_name} — {result.ticker}
{'═' * 50}
Total levels:      {ls.get('total_levels', 0)}
Confirmed (BPU):   {ls.get('confirmed_bpu', 0)}
Mirrors:           {ls.get('mirrors', 0)}
Invalidated:       {ls.get('invalidated_sawing', 0)}
Avg Score:         {ls.get('avg_score', 0):.1f}
Avg Touches:       {ls.get('avg_touches', 0):.1f}
"""
        return report.strip()

    @staticmethod
    def trade_list_report(result: BacktestResult) -> str:
        """Generate detailed trade list."""
        if not result.trades:
            return "No trades."

        lines = ["TRADE LIST — " + result.config_name + " — " + result.ticker]
        lines.append("═" * 120)
        lines.append(f"{'#':>3} {'Entry Time':>20} {'Dir':>5} {'Pattern':>7} "
                      f"{'Entry':>8} {'Exit':>8} {'Stop':>8} {'Target':>8} "
                      f"{'P&L':>10} {'R':>6} {'Reason':>12} {'Level':>8}")
        lines.append("-" * 120)

        for i, t in enumerate(result.trades, 1):
            lines.append(
                f"{i:>3} {str(t.entry_time):>20} "
                f"{'S' if t.direction == TradeDirection.SHORT else 'L':>5} "
                f"{t.signal.pattern.value:>7} "
                f"{t.entry_price:>8.2f} {t.exit_price:>8.2f} "
                f"{t.stop_price:>8.2f} {t.target_price:>8.2f} "
                f"{'${:.2f}'.format(t.pnl):>10} "
                f"{t.pnl_r:>5.2f}R "
                f"{t.exit_reason.value if t.exit_reason else 'open':>12} "
                f"{t.signal.level.price:>8.2f}"
            )

        return "\n".join(lines)

    @staticmethod
    def compare_results(baseline: BacktestResult, experiment: BacktestResult) -> str:
        """Compare two backtest results side by side."""
        b = baseline.performance
        e = experiment.performance

        def fmt(val, pct=False):
            if isinstance(val, float):
                return f"{val:.2f}{'%' if pct else ''}"
            return str(val)

        metrics = [
            ('Total Trades', 'total_trades', False),
            ('Win Rate', 'win_rate', True),
            ('Avg R', 'avg_r', False),
            ('Profit Factor', 'profit_factor', False),
            ('Sharpe', 'sharpe', False),
            ('Total P&L', 'total_pnl', False),
            ('Max Drawdown', 'max_drawdown_pct', True),
        ]

        lines = [f"COMPARISON: {baseline.config_name} vs {experiment.config_name}"]
        lines.append("═" * 60)
        lines.append(f"{'Metric':>20} {'Baseline':>15} {'Experiment':>15} {'Delta':>10}")
        lines.append("-" * 60)

        for name, key, is_pct in metrics:
            bv = b.get(key, 0)
            ev = e.get(key, 0)
            if is_pct and isinstance(bv, float):
                bv_display = f"{bv*100:.1f}%"
                ev_display = f"{ev*100:.1f}%"
                delta = f"{(ev-bv)*100:+.1f}%"
            else:
                bv_display = f"{bv:.2f}" if isinstance(bv, float) else str(bv)
                ev_display = f"{ev:.2f}" if isinstance(ev, float) else str(ev)
                delta = f"{ev-bv:+.2f}" if isinstance(bv, (int, float)) else "N/A"

            lines.append(f"{name:>20} {bv_display:>15} {ev_display:>15} {delta:>10}")

        return "\n".join(lines)


# Import here to avoid circular import issues with TradeDirection
from backtester.core.pattern_engine import TradeDirection
