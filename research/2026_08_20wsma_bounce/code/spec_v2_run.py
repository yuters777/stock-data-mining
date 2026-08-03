"""
SPEC v2 execution (frozen 2026-08-03, pre-data). One run, no iterations.
Unified episode scan per index: run-counter r resets on below-week AND after each
recorded episode. Touch at first week with Low<=SMA20 and prev_run>=1.
Signal = first weekly Close>SMA20 at/after touch. Classification by prev_run:
>=15 -> EVENT, 1..14 -> B1 control. Primary phenotype: lag<=4, ret4 available.
Pooled inference: mean-excess (events - B1), calendar-quarter block bootstrap, 10k, one-sided.
"""
import pandas as pd, numpy as np

rng = np.random.default_rng(20260803)
raw = pd.read_csv('/mnt/user-data/uploads/indices_daily_full.csv',
                  header=[0, 1], index_col=0, parse_dates=True)
markets = sorted({c[0] for c in raw.columns})

all_eps = []
meta = []
for m in markets:
    d = raw[m][['Low', 'Close', 'High']].astype(float).dropna(subset=['Close'])
    if len(d) == 0: continue
    w = pd.DataFrame({'Low': d['Low'].resample('W-FRI').min(),
                      'Close': d['Close'].resample('W-FRI').last(),
                      'High': d['High'].resample('W-FRI').max()}).dropna()
    w['SMA'] = w['Close'].rolling(20).mean()
    w = w.dropna()
    degen = float((w['High'] == w['Low']).mean())
    meta.append((m, w.index[0].date(), w.index[-1].date(), len(w), degen))
    above = (w['Close'] > w['SMA']).values
    low_le = (w['Low'] <= w['SMA']).values
    n = len(w)
    r, i = 0, 0
    while i < n:
        if low_le[i] and r >= 1:
            # touch with prev_run = r
            s = next((k for k in range(i, n) if above[k]), None)
            if s is None: break
            lag = s - i
            ret4 = w['Close'].iloc[s+4] / w['Close'].iloc[s] - 1 if s + 4 < n else np.nan
            mae = (w['Low'].iloc[s+1:s+5].min() / w['Close'].iloc[s] - 1) if s + 4 < n else np.nan
            all_eps.append(dict(market=m, touch=w.index[i], signal=w.index[s], prev_run=r,
                                lag=lag, ret4=ret4, mae=mae,
                                grp='EVENT' if r >= 15 else 'B1'))
            r, i = 0, s + 1
            continue
        r = r + 1 if above[i] else 0
        i += 1

ep = pd.DataFrame(all_eps)
ep['quarter'] = ep['signal'].dt.to_period('Q').astype(str)
prim = ep[(ep.lag <= 4) & ep.ret4.notna()].copy()
E, C = prim[prim.grp == 'EVENT'], prim[prim.grp == 'B1']

print('=== DATA ===')
for m, a, b, nw, dg in meta:
    print(f'{m:8s} {a} -> {b}  weeks={nw:5d}  High==Low share={dg:.0%}')

print('\n=== PRIMARY SAMPLE (lag<=4, completed) ===')
print(f'EVENTS N={len(E)}  wins={(E.ret4>0).mean():.1%}  mean={E.ret4.mean():+.2%}  median={E.ret4.median():+.2%}')
print(f'B1     N={len(C)}  wins={(C.ret4>0).mean():.1%}  mean={C.ret4.mean():+.2%}  median={C.ret4.median():+.2%}')
obs_mean_x = E.ret4.mean() - C.ret4.mean()
obs_win_x = (E.ret4 > 0).mean() - (C.ret4 > 0).mean()
print(f'observed excess: mean={obs_mean_x:+.2%}  win-rate={obs_win_x:+.1%}')

per_m = prim.groupby(['market', 'grp'])['ret4'].agg(['count', 'mean']).unstack()
print('\nper-market (count | mean):')
print(per_m.to_string(float_format=lambda x: f'{x:+.2%}' if abs(x) < 1 else f'{x:.0f}'))
ev_counts = E.groupby('market').size()
print(f'\nmarkets with >=2 events: {int((ev_counts>=2).sum())}  (counts: {ev_counts.to_dict()})')

# quarter-clustered bootstrap
quarters = prim['quarter'].unique()
by_q = {q: g for q, g in prim.groupby('quarter')}
draws_mean, draws_win = [], []
for _ in range(10000):
    qs = rng.choice(quarters, size=len(quarters), replace=True)
    sub = pd.concat([by_q[q] for q in qs])
    e, c = sub[sub.grp == 'EVENT'], sub[sub.grp == 'B1']
    if len(e) == 0 or len(c) == 0: continue
    draws_mean.append(e.ret4.mean() - c.ret4.mean())
    draws_win.append((e.ret4 > 0).mean() - (c.ret4 > 0).mean())
draws_mean, draws_win = np.array(draws_mean), np.array(draws_win)
p_mean = float((draws_mean <= 0).mean())
p_win = float((draws_win <= 0).mean())
print(f'\nbootstrap (quarter-clustered, {len(draws_mean)} valid draws):')
print(f'mean-excess: p(one-sided)={p_mean:.4f}  CI95=[{np.percentile(draws_mean,2.5):+.2%}, {np.percentile(draws_mean,97.5):+.2%}]')
print(f'win-excess:  p(one-sided)={p_win:.4f}')

print('\n=== SECONDARY (descriptive) ===')
for era, lo, hi in [('pre-2000', '1900', '2000'), ('2000-2012', '2000', '2013'), ('2013+', '2013', '2100')]:
    e = E[(E.signal >= lo) & (E.signal < hi)]; c = C[(C.signal >= lo) & (C.signal < hi)]
    if len(e): print(f'{era:10s} EVENTS N={len(e):3d} mean={e.ret4.mean():+.2%} | B1 N={len(c):3d} mean={c.ret4.mean():+.2%} | excess={e.ret4.mean()-c.ret4.mean():+.2%}')
print(f'event tail: worst ret4={E.ret4.min():+.2%}  worst MAE={E.mae.min():+.2%}')
dl = ep[(ep.lag > 4) & ep.ret4.notna() & (ep.grp == 'EVENT')]
print(f'delayed-reclaim events (lag>4): N={len(dl)}  mean={dl.ret4.mean():+.2%}' if len(dl) else 'delayed-reclaim events: none')
pend = ep[ep.ret4.isna() & (ep.grp == 'EVENT')]
print('pending/live events:', [(x.market, str(x.signal.date())) for x in pend.itertuples()])

# ---- DECISION per frozen §5 ----
print('\n=== DECISION (§5, frozen) ===')
pass_ok = (obs_mean_x >= 0.010) and (p_mean < 0.05) and (len(E) >= 40) and ((ev_counts >= 2).sum() >= 5)
kill = (obs_mean_x <= 0) or (p_mean >= 0.20)
print(f'PASS conditions: excess>=+1.0pp: {obs_mean_x>=0.010} | p<0.05: {p_mean<0.05} | N>=40: {len(E)>=40} | >=5 mkts >=2ev: {(ev_counts>=2).sum()>=5}')
print(f'KILL conditions: excess<=0: {obs_mean_x<=0} | p>=0.20: {p_mean>=0.20}')
print('VERDICT:', 'PASS' if pass_ok else ('KILL — permanent archive' if kill else 'GREY — archived, weak lean logged, no status'))

ep.to_csv('/home/claude/spec_v2_episodes.csv', index=False)
