# SPEC v2 — Cross-Market Confirmation: 20W-SMA Bounce (FROZEN 2026-08-03, pre-data)
# Status: PRE-REGISTERED. Authored before downloading any confirmation data.
# One run, no iterations. Any deviation must be documented in the results artifact.

## 1. Universe (fixed)
Confirmation set (pooled inference): ^GSPC, ^DJI, ^RUT, ^GDAXI, ^FTSE, ^N225, ^HSI, ^FCHI
Excluded from pooled inference: QQQ / ^NDX / ^IXIC (Nasdaq family = discovery sample; ^IXIC
reported as reference only if downloaded, never pooled).
Full available history per index; unequal depth accepted (unbalanced by design).

## 2. Event definition (identical to corrected QQQ spec)
- Weekly bars: W-FRI resample of daily (Low=min, Close=last), per index, unadjusted.
- SMA20 = 20-week SMA of weekly closes. ABOVE = Close > SMA20.
- Arming: episode-local rebuild counter r (r+=1 on ABOVE week, r=0 on below week,
  r=0 after every recorded event). Armed when r >= 15.
- TOUCH = weekly Low <= SMA20 while armed. SIGNAL = first weekly Close > SMA20 at/after touch.
- PRIMARY phenotype: reclaim lag <= 4 weeks. Lag > 4 recorded separately (descriptive only).
- Entry = signal-week close. Outcome ret4 = Close[t+4]/Close[t] - 1.

## 3. Baseline (matched, per Pro's construction)
B1 (primary control): same index, touch+reclaim events with lag <= 4 whose prior above-SMA
run < 15 weeks (same geometry, no streak precondition; same episode-local dedup).
B2 (reference only): all ABOVE weeks.
The tested quantity is the INCREMENT of the >=15-week precondition: events vs B1.

## 4. Primary test (pooled, pre-registered)
- Pool events and B1 controls across the 8 confirmation indices.
- Statistics: (a) win-rate difference, (b) mean ret4 difference (events minus B1).
- Inference: block bootstrap clustered on calendar quarter (resample quarters with
  replacement across the pooled panel), 10,000 draws, one-sided (events > B1).

## 5. Decision criteria (named now, before any data)
PASS -> "provisional cross-market context" (still NOT an overlay; next step would be
operator review) requires ALL of:
  - pooled mean excess vs B1 >= +1.0pp
  - bootstrap one-sided p < 0.05 on the mean-excess statistic
  - pooled primary event N >= 40, with >= 5 markets contributing >= 2 events each
KILL -> permanent archive, no re-cuts, no follow-up sessions:
  - mean excess <= 0, OR p >= 0.20
GREY (everything else): remains archived; logged as "weak cross-market lean", no status,
no further internal re-analysis of this pattern family.

## 6. Secondary outputs (descriptive only, never gate anything)
Per-market event table; per-market excess; era splits at 2000/2013 (fixed a priori);
failure tail (min ret4, MAE); delayed-reclaim subgroup summary.

## 7. Data honesty notes (declared in advance)
- Yahoo ^DJI truncated (~1992+); accepted.
- Price indices exclude dividends; consistent across events and controls, direction unbiased.
- Overlapping cross-market events (e.g., Oct-2018 firing globally) are the exact reason
  for calendar-quarter clustering; per-market counts reported so concentration is visible.
- If any index fails to download or has <25y history, it is dropped and named; criteria
  in §5 are NOT relaxed to compensate.
