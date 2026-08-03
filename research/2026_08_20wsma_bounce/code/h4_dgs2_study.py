"""
H4 (pre-registered 2026-08-03, direction-only, threshold-free):
  Failures of the 20W-SMA bounce pattern concentrate where the 2Y Treasury yield
  is in an uptrend at touch: dDGS2_26w = DGS2[touch_wk] - DGS2[touch_wk - 26wk] > 0.
  Sample: all completed events 1999-2026 (N=39). Caveat: narrative-derived from the
  same sample's failures -> even a pass is hypothesis-grade, not OOS.
  Tests: Mann-Whitney (fails > wins, directional) + sign split at 0.
"""
import pandas as pd, numpy as np
from scipy import stats

g = pd.read_csv('/mnt/user-data/uploads/DGS2.csv', parse_dates=['observation_date'],
                na_values='.').set_index('observation_date')['DGS2']
gw = g.resample('W-FRI').last().ffill()

ev = pd.read_csv('/home/claude/qqq_20wsma_events.csv', parse_dates=['touch', 'signal'])
done = ev.dropna(subset=['ret4']).copy()

def d26(dt):
    wk = pd.Timestamp(dt) + pd.offsets.Week(weekday=4) - pd.offsets.Week()  # that week's Friday
    wk = gw.index.asof(pd.Timestamp(dt))
    prev = wk - pd.Timedelta(weeks=26)
    return gw.asof(wk) - gw.asof(prev)

done['dgs2_26w'] = done['touch'].apply(d26)
done['fail'] = done['ret4'] <= 0

pd.set_option('display.width', 200)
print(done[['touch', 'signal', 'ret4', 'dgs2_26w', 'fail']].to_string(index=False,
      formatters={'ret4': '{:+.2%}'.format, 'dgs2_26w': '{:+.2f}pp'.format}))

f, w = done[done.fail], done[~done.fail]
print(f'\nfails (N={len(f)}): mean d26w={f.dgs2_26w.mean():+.2f}pp  median={f.dgs2_26w.median():+.2f}pp  rising in {int((f.dgs2_26w>0).sum())}/{len(f)}')
print(f'wins  (N={len(w)}): mean d26w={w.dgs2_26w.mean():+.2f}pp  median={w.dgs2_26w.median():+.2f}pp  rising in {int((w.dgs2_26w>0).sum())}/{len(w)}')
u = stats.mannwhitneyu(f.dgs2_26w, w.dgs2_26w, alternative='greater')
print(f'mann-whitney (fails > wins): p={u.pvalue:.3f}')

up, dn = done[done.dgs2_26w > 0], done[done.dgs2_26w <= 0]
print(f'\nsplit at 0: 2Y RISING  n={len(up)}  fail-rate={up.fail.mean():.0%}  mean ret4={up.ret4.mean():+.2%}')
print(f'            2Y FALLING n={len(dn)}  fail-rate={dn.fail.mean():.0%}  mean ret4={dn.ret4.mean():+.2%}')
fisher = stats.fisher_exact([[int(up.fail.sum()), len(up)-int(up.fail.sum())],
                             [int(dn.fail.sum()), len(dn)-int(dn.fail.sum())]], alternative='greater')
print(f'fisher exact (fail-rate rising > falling): p={fisher.pvalue:.3f}')

live_touch = pd.Timestamp('2026-07-31')
print(f'\nLIVE event touch 2026-07-31: dDGS2_26w = {d26(live_touch):+.2f}pp '
      f'(DGS2 now={gw.asof(gw.index.asof(live_touch)):.2f})')

done.to_csv('/home/claude/h4_events_dgs2.csv', index=False)
