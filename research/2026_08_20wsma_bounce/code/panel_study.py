"""
Panel study (pre-registered 2026-08-02/03):
  Events: QQQ weekly, streak>=15 above SMA20w -> touch (Low<=SMA) -> signal (first Close>SMA).
          Window: signals 2013-01-01+. Warmup from 2012-06 data.
  H1: post-signal 4w ticker returns rank by trailing 52w beta (terciles within event;
      per-event median per tercile; paired high-minus-low across events).
  H2: core breadth (tickers with data <=2012-12-31): share Close>own SMA20w at TOUCH week;
      pre-registered direction: lower in failing events (index ret4<0).
  H3: semis {NVDA,AMD,AVGO,TSM,MU}: share below own SMA at touch; higher in failing events.
  Ticker forward returns on Close (consistent with index study).
"""
import pandas as pd, numpy as np
from scipy import stats

raw = pd.read_csv('/mnt/user-data/uploads/tickers27_daily_2012_2026.csv',
                  header=[0, 1], index_col=0, parse_dates=True)
tickers = sorted({c[0] for c in raw.columns})
IDX = 'QQQ'

# weekly close/low per ticker
wc = pd.DataFrame({t: raw[(t, 'Close')].resample('W-FRI').last() for t in tickers})
wl = pd.DataFrame({t: raw[(t, 'Low')].resample('W-FRI').min() for t in tickers})
sma = wc.rolling(20).mean()
wret = wc.pct_change()

# ---- QQQ event scan ----
q, qs, ql = wc[IDX], sma[IDX], wl[IDX]
above = q > qs
streak = np.zeros(len(q), dtype=int)
for i in range(1, len(q)):
    streak[i] = streak[i-1] + 1 if above.iloc[i] else 0
streak[0] = int(above.iloc[0])

events, i, armed = [], 0, False
while i < len(q):
    if not armed:
        armed = streak[i] >= 15
        i += 1
        continue
    if pd.notna(qs.iloc[i]) and ql.iloc[i] <= qs.iloc[i]:
        t_i = i
        s_i = next((j for j in range(t_i, len(q)) if q.iloc[j] > qs.iloc[j]), None)
        if s_i is None:
            break
        r4 = q.iloc[s_i+4]/q.iloc[s_i]-1 if s_i+4 < len(q) else np.nan
        events.append(dict(touch_i=t_i, sig_i=s_i, touch=q.index[t_i], signal=q.index[s_i], idx_ret4=r4))
        armed, i = False, s_i + 1
    else:
        i += 1
ev = pd.DataFrame(events)
ev = ev[ev.signal >= '2013-01-01'].reset_index(drop=True)

# ---- core membership (first valid weekly close <= 2012-12-31) ----
first_bar = wc.apply(lambda s: s.first_valid_index())
core = [t for t in tickers if t != IDX and first_bar[t] is not None and first_bar[t] <= pd.Timestamp('2012-12-31')]
semis = ['NVDA', 'AMD', 'AVGO', 'TSM', 'MU']
print(f'core breadth set (N={len(core)}): {core}')
print(f'excluded from core: {sorted(set(tickers) - set(core) - {IDX})}\n')

# ---- per-event computations ----
rows, obs = [], []
for _, e in ev.iterrows():
    ti, si = int(e.touch_i), int(e.sig_i)
    # H2 breadth at touch
    b = [(wc[t].iloc[ti] > sma[t].iloc[ti]) for t in core if pd.notna(sma[t].iloc[ti])]
    breadth = np.mean(b)
    # H3 semis below own SMA at touch
    sb = [(wc[t].iloc[ti] < sma[t].iloc[ti]) for t in semis if pd.notna(sma[t].iloc[ti])]
    semis_below = np.mean(sb)
    # H1 per-ticker beta + fwd return at signal
    for t in tickers:
        if t == IDX: continue
        rt = wret[t].iloc[max(0, si-52):si].dropna()
        ri = wret[IDX].iloc[max(0, si-52):si]
        pair = pd.concat([rt, ri], axis=1).dropna()
        if len(pair) < 40 or si+4 >= len(wc) or pd.isna(wc[t].iloc[si]) or pd.isna(wc[t].iloc[si+4]):
            continue
        beta = pair.cov().iloc[0, 1] / pair.iloc[:, 1].var()
        obs.append(dict(signal=e.signal, ticker=t, beta=beta,
                        ret4=wc[t].iloc[si+4]/wc[t].iloc[si]-1))
    rows.append(dict(touch=e.touch.date(), signal=e.signal.date(), idx_ret4=e.idx_ret4,
                     breadth=breadth, semis_below=semis_below))

evt = pd.DataFrame(rows)
ob = pd.DataFrame(obs)

# terciles within event
ob['terc'] = ob.groupby('signal')['beta'].transform(lambda s: pd.qcut(s, 3, labels=['low', 'mid', 'high']))

print('=== EVENTS 2013+ (idx_ret4 NaN = live) ===')
print(evt.to_string(index=False, formatters={
    'idx_ret4': lambda x: f'{x:+.2%}' if pd.notna(x) else 'LIVE',
    'breadth': '{:.0%}'.format, 'semis_below': '{:.0%}'.format}))

done = evt.dropna(subset=['idx_ret4'])
win, fail = done[done.idx_ret4 > 0], done[done.idx_ret4 <= 0]

print('\n=== H1: beta terciles (per-event medians, then across-event stats) ===')
pm = ob.dropna(subset=['ret4']).groupby(['signal', 'terc'], observed=True)['ret4'].median().unstack()
print(pm.describe().loc[['mean', '50%']].to_string(float_format=lambda x: f'{x:+.2%}'))
hml = (pm['high'] - pm['low']).dropna()
print(f'high-minus-low spread: mean={hml.mean():+.2%}  positive in {int((hml>0).sum())}/{len(hml)} events  '
      f'wilcoxon p={stats.wilcoxon(hml, alternative="greater").pvalue:.3f}')

print('\n=== H2: core breadth at touch, wins vs fails ===')
print(f'wins  (N={len(win)}): mean={win.breadth.mean():.0%}  median={win.breadth.median():.0%}')
print(f'fails (N={len(fail)}): mean={fail.breadth.mean():.0%}  median={fail.breadth.median():.0%}')
u = stats.mannwhitneyu(win.breadth, fail.breadth, alternative='greater')
print(f'mann-whitney (wins>fails, directional, pre-registered): p={u.pvalue:.3f}')
print('fails detail:'); print(fail[['signal','idx_ret4','breadth','semis_below']].to_string(index=False,
      formatters={'idx_ret4':'{:+.2%}'.format,'breadth':'{:.0%}'.format,'semis_below':'{:.0%}'.format}))

print('\n=== H3: semis below own SMA at touch ===')
print(f'wins:  mean={win.semis_below.mean():.0%}   fails: mean={fail.semis_below.mean():.0%}')
u3 = stats.mannwhitneyu(fail.semis_below, win.semis_below, alternative='greater')
print(f'mann-whitney (fails>wins, directional): p={u3.pvalue:.3f}')

print('\n=== LIVE EVENT (touch 2026-07-31) readings ===')
live = evt.iloc[-1]
print(f"breadth={live.breadth:.0%} vs win-mean {win.breadth.mean():.0%} / fail-mean {fail.breadth.mean():.0%}")
print(f"semis_below={live.semis_below:.0%} vs win-mean {win.semis_below.mean():.0%} / fail-mean {fail.semis_below.mean():.0%}")
core_now = {t: 'ABOVE' if wc[t].iloc[-1] > sma[t].iloc[-1] else 'below' for t in core}
below_now = [t for t, v in core_now.items() if v == 'below']
print(f"core tickers below own 20W SMA at touch week: {below_now}")

evt.to_csv('/home/claude/panel_events.csv', index=False)
ob.to_csv('/home/claude/panel_ticker_obs.csv', index=False)
