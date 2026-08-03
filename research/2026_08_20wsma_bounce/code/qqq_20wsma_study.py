"""
QQQ 20-week SMA bounce study — pre-registered spec (2026-08-02):
  Weekly bars = W-FRI resample of daily (unadjusted OHLC).
  SMA20 = 20-week SMA of weekly Close. Regime ABOVE = Close > SMA20.
  Precondition: streak of >=15 consecutive weekly closes above SMA20.
  TOUCH  = first week after precondition where Low <= SMA20.
  SIGNAL = first weekly Close > SMA20 at-or-after touch week (entry at that close).
  Return = Close[t+4]/Close[t]-1 (t = signal week). MAE = min Low next 4w / entry - 1.
  Cooldown: next episode only after streak rebuilds to >=15.
  Base rates: unconditional & regime-conditional (Close>SMA20) 4-week forward returns.
"""
import pandas as pd, numpy as np
from scipy import stats

raw = pd.read_csv('/mnt/user-data/uploads/QQQ_daily_1999_2026.csv',
                  skiprows=[1, 2], index_col=0, parse_dates=True)
raw.index.name = 'Date'
d = raw[['Open', 'High', 'Low', 'Close', 'Adj Close']].astype(float)

w = pd.DataFrame({
    'Open':  d['Open'].resample('W-FRI').first(),
    'High':  d['High'].resample('W-FRI').max(),
    'Low':   d['Low'].resample('W-FRI').min(),
    'Close': d['Close'].resample('W-FRI').last(),
}).dropna()
w['SMA20'] = w['Close'].rolling(20).mean()
w = w.dropna().copy()
w['above'] = w['Close'] > w['SMA20']

# consecutive-weeks-above streak (as of each week's close)
streak = np.zeros(len(w), dtype=int)
for i in range(len(w)):
    streak[i] = streak[i-1] + 1 if (i > 0 and w['above'].iloc[i]) else (1 if w['above'].iloc[i] else 0)
w['streak'] = streak

# 4-week forward returns for base rates
w['ret4'] = w['Close'].shift(-4) / w['Close'] - 1

# ---- episode scan ----
events, i, armed = [], 0, False
while i < len(w):
    if not armed:
        if w['streak'].iloc[i] >= 15:
            armed = True
        i += 1
        continue
    # armed: look for touch
    if w['Low'].iloc[i] <= w['SMA20'].iloc[i]:
        touch_i = i
        # find signal: first close back above SMA at-or-after touch
        sig_i = None
        for j in range(touch_i, len(w)):
            if w['Close'].iloc[j] > w['SMA20'].iloc[j]:
                sig_i = j
                break
        if sig_i is None:
            events.append(dict(touch=w.index[touch_i].date(), signal=None, lag=None,
                               ret4=None, mae=None, note='NO_RECLAIM_YET'))
            break
        ent = w['Close'].iloc[sig_i]
        if sig_i + 4 < len(w):
            r4 = w['Close'].iloc[sig_i+4] / ent - 1
            mae = w['Low'].iloc[sig_i+1:sig_i+5].min() / ent - 1
        else:
            r4, mae = None, None
        events.append(dict(touch=w.index[touch_i].date(), signal=w.index[sig_i].date(),
                           lag=sig_i - touch_i, streak_at_touch=int(w['streak'].iloc[touch_i-1]),
                           entry=round(ent, 2), ret4=r4, mae=mae, note=''))
        armed = False
        i = sig_i + 1
    else:
        i += 1

ev = pd.DataFrame(events)
done = ev.dropna(subset=['ret4']).copy()
done['ret4'], done['mae'] = done['ret4'].astype(float), done['mae'].astype(float)

print('=== EVENTS (streak>=15 -> touch -> reclaim close) ===')
pd.set_option('display.width', 200)
print(ev.to_string(index=False,
      formatters={'ret4': lambda x: f'{x:+.2%}' if pd.notna(x) else '-',
                  'mae':  lambda x: f'{x:+.2%}' if pd.notna(x) else '-'}))

n = len(done); wins = int((done['ret4'] > 0).sum())
print(f'\nN={n}  wins={wins} ({wins/n:.0%})  mean={done.ret4.mean():+.2%}  '
      f'median={done.ret4.median():+.2%}  worst={done.ret4.min():+.2%}  worst_MAE={done.mae.min():+.2%}')

# ---- base rates ----
base = w['ret4'].dropna()
cond = w.loc[w['above'], 'ret4'].dropna()
for name, s in [('unconditional all-weeks', base), ('conditional Close>SMA20', cond)]:
    print(f'base rate [{name}]: P(+)={np.mean(s>0):.1%}  mean={s.mean():+.2%}  median={s.median():+.2%}  n={len(s)}')
p_binom = stats.binomtest(wins, n, float(np.mean(cond > 0)), alternative='greater').pvalue
t_p = stats.ttest_1samp(done['ret4'], cond.mean(), alternative='greater').pvalue
print(f'binomial test (wins vs conditional base): p={p_binom:.3f}')
print(f't-test (mean ret4 vs conditional mean):   p={t_p:.3f}')

# ---- Step 0: current state ----
print('\n=== STEP 0: CURRENT STATE ===')
tail = w.tail(8)[['Low', 'Close', 'SMA20', 'above', 'streak']]
print(tail.to_string(float_format=lambda x: f'{x:.2f}'))
last = w.iloc[-1]
print(f"\nlast weekly bar {w.index[-1].date()}: Close={last.Close:.2f} vs SMA20={last.SMA20:.2f} "
      f"-> {'ABOVE' if last.above else 'BELOW'}; streak={int(last.streak)}")
# streak just before the most recent touch/break in 2026
w26 = w.loc['2026']
first_break = w26[~w26['above']]
if len(first_break):
    fb = first_break.index[0]
    pos = w.index.get_loc(fb)
    print(f"first 2026 weekly close below SMA20: {fb.date()}; streak before it = {int(w['streak'].iloc[pos-1])} weeks")

ev.to_csv('/home/claude/qqq_20wsma_events.csv', index=False)
