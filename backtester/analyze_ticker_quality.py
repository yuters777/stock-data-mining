"""
Deep analysis: Why NVDA/TSLA lose while GOOGL/MSFT win.
Phase 2.2 REDO recommended config.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from collections import defaultdict

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.data_types import ExitReason, PatternType, SignalDirection, LevelType, LevelStatus

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']
START = '2025-02-10'
END = '2026-02-01'

config = BacktestConfig(
    level_config=LevelDetectorConfig(
        fractal_depth=10, tolerance_cents=0.05, tolerance_pct=0.001,
        atr_period=5, min_level_score=5,
        cross_count_invalidate=5, cross_count_window=30,
    ),
    pattern_config=PatternEngineConfig(
        tail_ratio_min=0.15, lp2_engulfing_required=True,
        clp_min_bars=3, clp_max_bars=7,
    ),
    filter_config=FilterChainConfig(
        atr_block_threshold=0.10, atr_entry_threshold=0.40,
        enable_volume_filter=True, enable_time_filter=True,
        enable_squeeze_filter=True,
    ),
    risk_config=RiskManagerConfig(
        min_rr=3.0, max_stop_atr_pct=0.15,
        capital=100000.0, risk_pct=0.003,
    ),
    trade_config=TradeManagerConfig(),
    tier_config={
        'mode': '2tier_trail', 't1_pct': 0.30, 'trail_factor': 0.7,
        'trail_activation_r': 0.0, 'min_rr': 1.5,
    },
    direction_filter=None,
    name="ticker_analysis",
)


def load_data():
    frames = []
    for ticker in TICKERS:
        path = os.path.join(DATA_DIR, f'{ticker}_data.csv')
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)
        frames.append(df)
    return pd.concat(frames, ignore_index=True).sort_values(
        ['Ticker', 'Datetime']).reset_index(drop=True)


def print_trades(trades, label):
    if not trades:
        print(f"  No {label} trades.")
        return
    print(f"\n  {label} ({len(trades)} trades):")
    print(f"  {'#':>3} {'Date':>12} {'HH:MM':>5} {'D':>1} {'Pat':>3} "
          f"{'Entry':>8} {'StopD':>6} {'MFE_R':>6} {'MAE_R':>6} "
          f"{'P&L':>8} {'R':>6} {'Exit':>14} {'LvlT':>5} {'Scr':>4}")
    print(f"  {'-'*105}")
    for i, t in enumerate(trades):
        sd = t.risk_params.stop_distance
        mfe_r = t.max_favorable / sd if sd > 0 else 0
        mae_r = t.max_adverse / sd if sd > 0 else 0
        d = 'S' if t.direction == SignalDirection.SHORT else 'L'
        pat = t.signal.pattern.value[:3]
        lt = t.signal.level.level_type.value[:3]
        ex = t.exit_reason.value if t.exit_reason else '?'
        print(f"  {i+1:>3} {t.entry_time.strftime('%Y-%m-%d'):>12} "
              f"{t.entry_time.strftime('%H:%M'):>5} {d:>1} {pat:>3} "
              f"{t.entry_price:>8.2f} {sd:>6.2f} {mfe_r:>5.1f}R {mae_r:>5.1f}R "
              f"${t.pnl:>7.2f} {t.pnl_r:>5.2f}R {ex:>14} {lt:>5} {t.signal.level.score:>4.0f}")


def analyze_group(trades, label):
    if not trades:
        return
    long_t = [t for t in trades if t.direction == SignalDirection.LONG]
    short_t = [t for t in trades if t.direction == SignalDirection.SHORT]
    lp1 = [t for t in trades if t.signal.pattern == PatternType.LP1]
    lp2 = [t for t in trades if t.signal.pattern == PatternType.LP2]
    sup = [t for t in trades if t.signal.level.level_type == LevelType.SUPPORT]
    res = [t for t in trades if t.signal.level.level_type == LevelType.RESISTANCE]
    mir = [t for t in trades if t.signal.level.level_type == LevelType.MIRROR]
    sds = [t.risk_params.stop_distance for t in trades]
    mfes = [t.max_favorable / t.risk_params.stop_distance
            if t.risk_params.stop_distance > 0 else 0 for t in trades]
    scores = [t.signal.level.score for t in trades]
    hours = defaultdict(int)
    for t in trades:
        hours[t.entry_time.hour] += 1

    print(f"\n  {label} SUMMARY ({len(trades)} trades):")
    print(f"    Direction: {len(long_t)}L / {len(short_t)}S")
    print(f"    Pattern:   {len(lp1)} LP1, {len(lp2)} LP2")
    print(f"    Level:     {len(sup)} support, {len(res)} resistance, {len(mir)} mirror")
    print(f"    MFE (R):   mean={np.mean(mfes):.2f}, median={np.median(mfes):.2f}")
    print(f"    Stop dist: mean=${np.mean(sds):.2f}")
    print(f"    Lvl score: mean={np.mean(scores):.1f}")
    print(f"    Hours:     ", end="")
    for h in sorted(hours):
        print(f"{h}h={hours[h]} ", end="")
    print()


def main():
    print("=" * 90)
    print("DEEP ANALYSIS: Why NVDA/TSLA Lose, GOOGL/MSFT Win")
    print("=" * 90)

    m5_df = load_data()
    bt = Backtester(config)
    result = bt.run(m5_df, start_date=START, end_date=END)
    trades = result.trades
    daily_df = bt.daily_df

    # ═══════════════════════════════════════════════════════════════════
    # 1. NVDA
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("1. NVDA — ALL TRADES")
    print("=" * 90)
    nvda = sorted([t for t in trades if t.signal.ticker == 'NVDA'], key=lambda t: t.entry_time)
    print_trades(nvda, "NVDA ALL")
    analyze_group([t for t in nvda if t.pnl <= 0], "NVDA LOSERS")
    analyze_group([t for t in nvda if t.pnl > 0], "NVDA WINNERS")

    # ═══════════════════════════════════════════════════════════════════
    # 2. TSLA
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("2. TSLA — ALL TRADES")
    print("=" * 90)
    tsla = sorted([t for t in trades if t.signal.ticker == 'TSLA'], key=lambda t: t.entry_time)
    print_trades(tsla, "TSLA ALL")
    analyze_group([t for t in tsla if t.pnl <= 0], "TSLA LOSERS")
    analyze_group([t for t in tsla if t.pnl > 0], "TSLA WINNERS")

    # ═══════════════════════════════════════════════════════════════════
    # 3. GOOGL
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("3. GOOGL — ALL TRADES")
    print("=" * 90)
    googl = sorted([t for t in trades if t.signal.ticker == 'GOOGL'], key=lambda t: t.entry_time)
    print_trades(googl, "GOOGL ALL")
    analyze_group([t for t in googl if t.pnl > 0], "GOOGL WINNERS")
    analyze_group([t for t in googl if t.pnl <= 0], "GOOGL LOSERS")

    # ═══════════════════════════════════════════════════════════════════
    # 3b. MSFT (profitable comparison)
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("3b. MSFT — ALL TRADES")
    print("=" * 90)
    msft = sorted([t for t in trades if t.signal.ticker == 'MSFT'], key=lambda t: t.entry_time)
    print_trades(msft, "MSFT ALL")
    analyze_group([t for t in msft if t.pnl > 0], "MSFT WINNERS")

    # ═══════════════════════════════════════════════════════════════════
    # 4. VOLATILITY COMPARISON
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("4. VOLATILITY COMPARISON (ATR_D1 / Price)")
    print("=" * 90)
    print(f"\n  {'Ticker':>6} {'AvgPrice':>10} {'AvgATR':>8} {'ATR/Pr%':>8} "
          f"{'AvgStopD':>9} {'Stop/Pr%':>9} {'AvgRng%':>8} {'MaxStopCap':>11}")
    print(f"  {'-'*80}")
    for ticker in TICKERS:
        td = daily_df[daily_df['Ticker'] == ticker]
        if td.empty:
            continue
        avg_price = td['Close'].mean()
        if 'ATR' in td.columns:
            avg_atr = td['ATR'].mean()
        else:
            tr = pd.concat([
                td['High'] - td['Low'],
                abs(td['High'] - td['Close'].shift(1)),
                abs(td['Low'] - td['Close'].shift(1)),
            ], axis=1).max(axis=1)
            avg_atr = tr.rolling(10).mean().mean()
        atr_pct = avg_atr / avg_price * 100
        avg_range = ((td['High'] - td['Low']) / td['Close']).mean() * 100
        tt = [t for t in trades if t.signal.ticker == ticker]
        avg_stop = np.mean([t.risk_params.stop_distance for t in tt]) if tt else 0
        stop_pct = avg_stop / avg_price * 100 if avg_price > 0 else 0
        # max_stop_atr_pct = 0.15 means stop ≤ 15% of ATR
        max_stop_cap = 0.15 * avg_atr
        print(f"  {ticker:>6} ${avg_price:>9.2f} ${avg_atr:>7.2f} {atr_pct:>7.2f}% "
              f"${avg_stop:>8.2f} {stop_pct:>8.3f}% {avg_range:>7.2f}% "
              f"${max_stop_cap:>10.2f}")

    # ═══════════════════════════════════════════════════════════════════
    # 5. LEVEL QUALITY PER TICKER
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("5. LEVEL QUALITY PER TICKER")
    print("=" * 90)
    print(f"\n  {'Ticker':>6} {'Lvls':>5} {'AvgScr':>7} {'Mir%':>6} {'Inv%':>6} "
          f"{'AvgTch':>7} {'Tr/Lvl':>7}")
    print(f"  {'-'*55}")
    for ticker in TICKERS:
        tl = [l for l in bt.levels if l.ticker == ticker]
        if not tl:
            continue
        tt = [t for t in trades if t.signal.ticker == ticker]
        print(f"  {ticker:>6} {len(tl):>5} {np.mean([l.score for l in tl]):>7.1f} "
              f"{sum(1 for l in tl if l.is_mirror)/len(tl)*100:>5.1f}% "
              f"{sum(1 for l in tl if l.status==LevelStatus.INVALIDATED)/len(tl)*100:>5.1f}% "
              f"{np.mean([l.touches for l in tl]):>7.1f} {len(tt)/max(len(tl),1):>7.1f}")

    # Traded level scores: winners vs losers
    print(f"\n  Traded level scores (winners vs losers):")
    for ticker in TICKERS:
        tt = [t for t in trades if t.signal.ticker == ticker]
        if not tt:
            continue
        w_s = [t.signal.level.score for t in tt if t.pnl > 0]
        l_s = [t.signal.level.score for t in tt if t.pnl <= 0]
        w_str = f"{np.mean(w_s):.1f}" if w_s else "N/A"
        l_str = f"{np.mean(l_s):.1f}" if l_s else "N/A"
        print(f"    {ticker}: all={np.mean([t.signal.level.score for t in tt]):.1f} | "
              f"W={w_str} | L={l_str}")

    # ═══════════════════════════════════════════════════════════════════
    # 6. DIRECTION ANALYSIS
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("6. DIRECTION ANALYSIS PER TICKER")
    print("=" * 90)
    print(f"\n  {'Ticker':>6} {'Dir':>5} {'N':>4} {'W':>3} {'L':>3} {'WR%':>6} "
          f"{'PF':>7} {'P&L':>10} {'MFE_R':>7} {'MAE_R':>7}")
    print(f"  {'-'*65}")
    for ticker in TICKERS:
        for dn, dv in [('LONG', SignalDirection.LONG), ('SHORT', SignalDirection.SHORT)]:
            tt = [t for t in trades if t.signal.ticker == ticker and t.direction == dv]
            if not tt:
                continue
            w = sum(1 for t in tt if t.pnl > 0)
            l = len(tt) - w
            wr = w / len(tt) * 100
            gp = sum(t.pnl for t in tt if t.pnl > 0)
            gl = abs(sum(t.pnl for t in tt if t.pnl < 0))
            pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0)
            pnl = sum(t.pnl for t in tt)
            mfe = np.mean([t.max_favorable/t.risk_params.stop_distance
                           if t.risk_params.stop_distance > 0 else 0 for t in tt])
            mae = np.mean([t.max_adverse/t.risk_params.stop_distance
                           if t.risk_params.stop_distance > 0 else 0 for t in tt])
            print(f"  {ticker:>6} {dn:>5} {len(tt):>4} {w:>3} {l:>3} {wr:>5.1f}% "
                  f"{pf:>7.2f} ${pnl:>9.2f} {mfe:>6.2f}R {mae:>6.2f}R")

    # ═══════════════════════════════════════════════════════════════════
    # 7. SAME-LEVEL REPEAT LOSSES
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("7. SAME-LEVEL REPEAT LOSSES (NVDA & TSLA)")
    print("=" * 90)
    for ticker in ['NVDA', 'TSLA']:
        tt = sorted([t for t in trades if t.signal.ticker == ticker], key=lambda t: t.entry_time)
        level_groups = defaultdict(list)
        for t in tt:
            level_groups[f"{t.signal.level.price:.2f}"].append(t)
        print(f"\n  {ticker}:")
        for lp in sorted(level_groups):
            g = level_groups[lp]
            if len(g) >= 2:
                w = sum(1 for t in g if t.pnl > 0)
                l = len(g) - w
                pnl = sum(t.pnl for t in g)
                print(f"    ${lp}: {len(g)} trades ({w}W/{l}L) P&L=${pnl:.2f}")

    # ═══════════════════════════════════════════════════════════════════
    # 8. HYPOTHESIS: EXCLUDE NVDA + TSLA
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("8. HYPOTHESIS: Portfolio WITHOUT NVDA and TSLA")
    print("=" * 90)
    for label, tt in [("FULL 6-ticker", trades),
                      ("EXCL NVDA+TSLA (4-ticker)", [t for t in trades if t.signal.ticker not in ('NVDA','TSLA')])]:
        if not tt:
            continue
        n = len(tt)
        w = sum(1 for t in tt if t.pnl > 0)
        gp = sum(t.pnl for t in tt if t.pnl > 0)
        gl = abs(sum(t.pnl for t in tt if t.pnl < 0))
        pf = gp / gl if gl > 0 else 0
        pnl = sum(t.pnl for t in tt)
        avg_r = np.mean([t.pnl_r for t in tt])
        # Drawdown
        eq = 100000.0; peak = eq; max_dd = 0
        for t in sorted(tt, key=lambda x: x.entry_time):
            eq += t.pnl; peak = max(peak, eq)
            dd = (peak - eq) / peak; max_dd = max(max_dd, dd)
        # Sharpe
        daily = defaultdict(float)
        for t in tt:
            daily[t.entry_time.strftime('%Y-%m-%d')] += t.pnl
        dr = list(daily.values())
        sharpe = np.mean(dr) / np.std(dr) * np.sqrt(252) if len(dr) > 1 and np.std(dr) > 0 else 0
        print(f"\n  {label}:")
        print(f"    Trades: {n}, Winners: {w} ({w/n*100:.1f}%)")
        print(f"    PF:     {pf:.2f}")
        print(f"    P&L:    ${pnl:.2f}")
        print(f"    AvgR:   {avg_r:.2f}")
        print(f"    MaxDD:  {max_dd*100:.2f}%")
        print(f"    Sharpe: {sharpe:.2f}")

    # ═══════════════════════════════════════════════════════════════════
    # 9. KEY METRIC COMPARISON TABLE
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("9. TICKER COMPARISON MATRIX")
    print("=" * 90)
    print(f"\n  {'Ticker':>6} {'N':>4} {'WR%':>6} {'PF':>6} {'P&L':>10} "
          f"{'AvgMFE':>7} {'AvgMAE':>7} {'MFE>2R%':>8} {'AvgScr':>7} {'ATR/Pr%':>8}")
    print(f"  {'-'*80}")
    for ticker in TICKERS:
        tt = [t for t in trades if t.signal.ticker == ticker]
        if not tt:
            continue
        w = sum(1 for t in tt if t.pnl > 0)
        gp = sum(t.pnl for t in tt if t.pnl > 0)
        gl = abs(sum(t.pnl for t in tt if t.pnl < 0))
        pf = gp / gl if gl > 0 else 0
        pnl = sum(t.pnl for t in tt)
        mfes = [t.max_favorable/t.risk_params.stop_distance
                if t.risk_params.stop_distance > 0 else 0 for t in tt]
        maes = [t.max_adverse/t.risk_params.stop_distance
                if t.risk_params.stop_distance > 0 else 0 for t in tt]
        mfe2 = sum(1 for m in mfes if m >= 2.0) / len(mfes) * 100
        scr = np.mean([t.signal.level.score for t in tt])
        td = daily_df[daily_df['Ticker'] == ticker]
        avg_price = td['Close'].mean()
        if 'ATR' in td.columns:
            avg_atr = td['ATR'].mean()
        else:
            tr = pd.concat([td['High']-td['Low'], abs(td['High']-td['Close'].shift(1)),
                            abs(td['Low']-td['Close'].shift(1))], axis=1).max(axis=1)
            avg_atr = tr.rolling(10).mean().mean()
        atr_pct = avg_atr / avg_price * 100
        print(f"  {ticker:>6} {len(tt):>4} {w/len(tt)*100:>5.1f}% {pf:>5.2f} ${pnl:>9.2f} "
              f"{np.mean(mfes):>6.2f}R {np.mean(maes):>6.2f}R {mfe2:>7.1f}% "
              f"{scr:>7.1f} {atr_pct:>7.2f}%")

    print("\n" + "=" * 90)
    print("DONE")
    print("=" * 90)


if __name__ == '__main__':
    main()
