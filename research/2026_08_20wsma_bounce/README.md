# 20W-SMA Bounce Research Arc — 2026-08-02/03

**Status: ARCHIVE (DR verdict 9.5/10-scored session) + GREY cross-market annotation (frozen SPEC v2).**
Pattern has NO framework influence: no overlay, no bias, no sizing. Family closed to internal
re-analysis per SPEC v2 §5. Reopening requires a new pre-registered spec on future OOS data.
Full narrative: VLog bundle (pending at commit time). Live observation: QQQ signal 2026-07-31
@ 687.99 → single measurement at 2026-08-28 close, then done. (^N225 fired same-date signal.)

## Placement
`stock-data-mining/research/2026_08_20wsma_bounce/` (source of truth, workstation)
→ `git push` → `/opt/market-research` via `git pull` (VPS descendant clone).
NOT loaded into research.db (uncertified yfinance data; certification + seal discipline applies
there). NOT related to /opt/autobacktest-agent.

## Data provenance (uncertified, yfinance daily, downloaded 2026-08-02/03; DGS2 = FRED)
| file | sha256 |
|---|---|
| data/QQQ_daily_1999_2026.csv | a646876b32cf3f794f689effa0de8e6402f90653e70a53f7bbcb4a6c02811a5c |
| data/tickers27_daily_2012_2026.csv | 5c512e2f1218f9523052cee2f2100a51080f8bf23664bc02c3878fe29eae3038 |
| data/indices_daily_full.csv | ac82485a32fe8cfcfcf92dc1aac7c2796806591e55a5625ea031126bf030d477 |
| data/DGS2.csv | ea8b91463644518bc542999584dfb0cdcfe82b08fe16a5c5303139f5adde7c5b |

Downloaders (reproducible):
- `yf.download('QQQ', start='1999-03-10', auto_adjust=False)`
- `yf.download('AAPL MSFT GOOGL AMZN META NVDA TSLA AMD SMCI PLTR AVGO ARM TSM MU INTC COST COIN MSTR MARA C GS V BA JPM BABA JD BIDU QQQ', start='2012-06-01', auto_adjust=False, group_by='ticker')`
- `yf.download('^GSPC ^DJI ^RUT ^GDAXI ^FTSE ^N225 ^HSI ^FCHI', start='1920-01-01', auto_adjust=False, group_by='ticker')`
- FRED: https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2

## Contents
- `code/` — qqq_20wsma_study.py (index study; contains the CRITICAL cooldown defect, kept
  verbatim for the record), panel_study.py (H1-H3), h4_dgs2_study.py (H4), spec_v2_run.py
  (corrected episode-local cooldown; executes frozen SPEC v2).
- `results/` — qqq_20wsma_events.csv (defective 39-census, historical record),
  panel_events.csv, panel_ticker_obs.csv, h4_events_dgs2.csv, spec_v2_episodes.csv
  (authoritative cross-market episode census: 225 events / 946 B1 controls).
- `spec/SPEC_v2_CrossMarket_20WSMA_FROZEN.md` — pre-registered before data; binding.
- `dr/` — DR_Prompt_20WSMA_Bounce_ChatGPT_Pro.md (sent; report scored 9.5/10, verdict
  ARCHIVE), DR_FollowUp_H4_Reconciliation.md (authored, NOT sent — superseded by verdict).

## Key numbers (for future reference without re-running)
- Corrected QQQ census: N=26, 21 wins (80.8%), mean +2.37% (defective census was N=39).
- Cross-market (8 indices, frozen run): events N=225 mean +1.01% vs matched B1 N=946
  mean +0.39%; excess +0.62pp, quarter-clustered bootstrap p=0.081 (mean, decision metric);
  win-excess +9.8pp p=0.013 (observational only, not the pre-registered metric).
- Era: pre-2000 excess −0.61pp; 2000-2012 +2.03pp; 2013+ +1.14pp. Tail: worst −31.14%.
- H1 weak/unconfirmed · H2/H3 narrow constructions unsupported (broad concepts untested)
  · H4 direction-aligned, unconfirmed (p=0.159).
- Inversion note (hypothesis-grade, queued): touch episodes underperform ordinary
  above-SMA weeks → touch as risk marker, not opportunity.

## Lessons (candidate, operator promotion pending per #68)
A cooldown defined on a state variable the event does not perturb is not a cooldown
(touch-hold weeks never reset the streak → re-arm was vacuous; 13/39 events were phantoms).
