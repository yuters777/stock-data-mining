# S14-CC Cross-Validation — Part 4: Validation, Testing & Risk (CV-11 to CV-15)
# Date: March 20, 2026
# Validator: Claude Code (Opus 4.6)

---

## CV-11: Golden-Day Replay Test Structure

The replay test is the single most valuable test you will write — it proves that the system produces the same framework states you and Claude observed manually during live sessions. Structure it as a **deterministic pipeline with frozen inputs and timestamped expected outputs**, not as a traditional unit test.

**Input format:** Capture raw inputs as JSON fixture files per day. Each file contains: (1) M5 bars for all 25 tickers for the full session (16:30-23:00 IST), sourced from your existing AV data in `bars_m5`, (2) news items with their raw text, channel, and Tier 1 scores, (3) IB macro state snapshots (VIX, VVIX, VX1! at each 5-min mark — for Phase 1b replay you may need to reconstruct these from TradingView or manual notes since IB was not live), and (4) the `research_config_version` parameters that were active that day. The fixture file is a complete set of everything the freeze step would read — no network calls, no live DB.

**Expected output format:** A YAML or JSON file keyed by wall-clock timestamps (aligned to 5-min boundaries), each entry containing the expected framework states at that cycle:

```yaml
# tests/replay/day4_expected.yaml
day: "2026-03-12"
session: "Day 4"
notes: "Override activated twice, NVDA EMA cross at ~17:45 IST"

checkpoints:
  - time_utc: "2026-03-12T11:15:00Z"  # 16:45 IST, first cycle after open
    ema_state:
      NVDA: {gate: "BULL", tss: 0.72}
      TSLA: {gate: "BEAR", tss: 0.35}
    override: {state: "OFF", composite_score: 1.8}
    zone: {zone_id: 1, name: "Opening"}
    policy_decisions:
      NVDA: {action: "GO", score: 8, blocked_by: null}
      TSLA: {action: "BLOCKED", score: 3, blocked_by: "ema_gate_bear"}

  - time_utc: "2026-03-12T14:22:00Z"  # the VIX spike moment
    override: {state: "ON", composite_score: 6.2}
    policy_decisions:
      NVDA: {action: "BLOCKED", score: 8, blocked_by: "override_on"}
```

**Replay runner:** Feed the fixture file into the compute pipeline cycle-by-cycle. For each checkpoint timestamp, compare actual vs expected states. Use **approximate matching** — EMA values within ±0.5%, Override composite score within ±0.3, gate/zone/action must be exact. This tolerance accounts for floating-point differences in bar synthesis and minor parameter rounding. The replay runner should output a diff report: green for matches, red for mismatches, yellow for "close but outside tolerance." Do not require 100% match on day one — the goal is to identify where the system diverges from manual observations and understand *why*. A mismatch often reveals that the manual observation was imprecise ("Override activated around 2:20" vs system saying 2:15), not that the system is wrong. Track the match rate per module: "Override: 12/14 checkpoints matched, EMA: 25/25, Zone: 14/14, Policy: 11/14." This gives you a per-module confidence score.

**Practical tip:** You probably don't have IB macro data for Day 4/5 since IB was not connected. For Phase 1b replay, hardcode VIX/VVIX values at each checkpoint from your TradingView screenshots or session notes. This is imperfect but sufficient — the replay test proves the *computation logic* is correct given known inputs, even if Phase 1b production will use live IB data.

---

## CV-12: Performance Budget — 25-Ticker Cycle on Hetzner CX22

The target of <30 seconds is **extremely conservative — the actual cycle should complete in under 2 seconds.** Here is the breakdown.

**Freeze step (step 3):** One SQLite read transaction reading ~25 rows from `bars_m5` (latest bar per ticker), ~25 rows from `ema_state`, 1 row from `override_state`, 1 row from `zone_state`, ~5-10 rows from recent `news_analysis`, 1 row from `config_versions`. Total: ~60-70 rows. SQLite reads this from WAL in **<10ms** — this is trivially fast on any hardware. The data fits in a single page cache read.

**Compute step (step 5):** This is pure CPU math on in-memory data:
- *4H bar synthesis:* For each ticker, aggregate the last 48 M5 bars into one 4H bar. 25 tickers × 48 bars = 1200 iterations of simple OHLCV aggregation. **<5ms.**
- *EMA 9/21:* Two exponential moving averages per ticker on the 4H series. 25 tickers × 2 EMAs = 50 EMA computations, each over ~20-50 data points. **<2ms.** If using numpy, sub-millisecond.
- *RSI + ADX + Squeeze:* Standard indicator calculations per ticker. Even without numpy, pure Python loops over 50-bar windows for 25 tickers complete in **<20ms.**
- *Override 3.0 (7 components):* z-score calculations on VIX/VVIX deltas (a few arithmetic operations), term structure check (one comparison), breadth (one loop over tickers), OilCatalyst/EventPenalty/GeoPenalty (lookups and threshold checks). **<5ms total.**
- *Zone detection:* One time comparison against 5 zone boundaries. **<1ms.**
- *Policy Engine:* 25 tickers × 13 rejection checks = 325 boolean evaluations. **<5ms.**
- *Snapshot assembly + shadow portfolio decisions:* Dataclass construction and a few comparisons. **<5ms.**

**Total compute: ~40-50ms.** Even if you 10x this for Python overhead, interpreter warmth, and GC pauses, you are at ~500ms worst case.

**Atomic write (step 6):** One SQLite transaction writing ~60-80 rows across multiple tables (cycle metadata, 25 module state rows, 2 snapshot rows, 25 shadow decisions, ~30 event log rows). SQLite WAL handles this in **<50ms** for the write itself, plus **<20ms** for the WAL commit (fsync). Total: **<100ms.**

**Grand total: <700ms p50, <1.5s p95** on the Hetzner CX22. The 30-second target is off by more than an order of magnitude. The only scenario where you approach even 5 seconds is if you accidentally make network calls inside the compute step (violating the freeze-compute-write contract) or if SQLite busy-waits on a write lock held by the ingest process. Both are bugs, not performance bottlenecks. The real bottleneck is **not in the compute cycle at all** — it is in the ingest layer: Alpha Vantage API calls (network latency, 75 req/min rate limit forcing sequential fetches) and Tier 2 Claude API calls (~1-3 seconds each). But these run asynchronously outside the compute cycle, so they do not affect cycle timing. Set a `PRAGMA busy_timeout = 5000` on the compute connection and a performance counter that logs p50/p95 cycle time to `event_log`. If you ever see a cycle exceed 5 seconds, investigate — something is wrong.

---

## CV-13: Config Versioning Implementation

Use **explicit stamping in the cycle orchestrator**, not middleware. Middleware that intercepts every DB write is fragile (easy to bypass, hard to debug, unclear ownership). Instead, the cycle orchestrator reads the current `research_config_version` during the freeze step and passes it through as a field on `FrozenState`. Every write in the atomic transaction includes this version because it flows from the frozen state — modules do not fetch the version independently.

Concrete implementation with three version types:

```python
# config/versions.py
from dataclasses import dataclass

@dataclass(frozen=True)
class SystemVersions:
    deploy_version: str           # git SHA or semver tag, set at startup
    research_config_version: int  # auto-incremented on parameter change
    tier2_schema_version: int     # bumped when Tier 2 tool schema changes

# Set once at process startup, never changes during runtime
DEPLOY_VERSION = subprocess.check_output(
    ["git", "rev-parse", "--short", "HEAD"]
).decode().strip()
```

```sql
-- config_versions table
CREATE TABLE config_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    effective_from TEXT NOT NULL,       -- ISO8601 UTC
    effective_until TEXT,               -- NULL = currently active
    parameters TEXT NOT NULL,           -- JSON blob of all tunable parameters
    change_description TEXT NOT NULL,   -- human-readable: "lowered Override threshold from 4.0 to 3.5"
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Every cycle snapshot references the config it used
CREATE TABLE snapshots (
    cycle_id TEXT PRIMARY KEY,
    deploy_version TEXT NOT NULL,
    research_config_version INTEGER NOT NULL REFERENCES config_versions(id),
    tier2_schema_version INTEGER NOT NULL,
    frozen_at TEXT NOT NULL,
    raw_snapshot TEXT NOT NULL,         -- JSON
    filtered_snapshot TEXT NOT NULL,    -- JSON
    -- ...
);

-- Shadow positions reference the config they were opened under
CREATE TABLE positions (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    entry_cycle_id TEXT NOT NULL REFERENCES snapshots(cycle_id),
    research_config_version INTEGER NOT NULL,
    -- ...
);
```

The flow: (1) At freeze time, read the row from `config_versions` where `effective_until IS NULL` — that is the active config. Store its `id` as `research_config_version` in `FrozenState`. (2) At write time, stamp every snapshot row and every shadow position with this version. (3) `deploy_version` is the git short SHA captured at process startup — it changes only on redeploy. (4) `tier2_schema_version` is a constant in the Tier 2 module, bumped manually when you change the tool schema. It is written alongside every `news_analysis` row.

To change a research config parameter: insert a new row into `config_versions` with the new parameters and set `effective_until` on the old row. The next compute cycle picks up the new version automatically at freeze. This gives you a complete audit trail — you can query "what parameters were active when this shadow trade was opened" and "how would last week's trades differ under the new config" by replaying with a different `config_versions.id`.

---

## CV-14: S15 Phase 1b Scope — Realism Assessment

The 8-core scope is **achievable in 2 weeks for a focused solo developer, but tight.** Here is my honest breakdown by component:

| # | Component | Effort estimate | Notes |
|---|-----------|----------------|-------|
| 1 | IB Gateway setup | 2-3 days | First-time IBC setup, Java tuning, systemd, connectivity debugging. Biggest unknown. Budget extra for IB account subscription activation delays. |
| 2 | Minimal IB bridge | 1-2 days | ~300 lines wrapper (per CV-4), but testing against live IB Gateway has friction |
| 3 | EMA state computation | 1 day | Straightforward math, well-defined inputs/outputs |
| 4 | Zone state | 0.5 day | Time comparisons + DST lookup table |
| 5 | Policy Engine | 1-2 days | 13 rejections are individually simple but the full matrix needs careful testing |
| 6 | Immutable compute cycle skeleton | 1-2 days | The orchestrator (7-step cycle) — glues everything together |
| 7 | Tier 2 structured outputs | 1 day | Tool use schema (per CV-8), mostly copy-paste with testing |
| 8 | Replay test + critical tests | 2-3 days | Fixture creation from manual notes is the slow part |

**Total: 10-15 working days.** Two calendar weeks is feasible if you are coding full-time with no other obligations. If you have a day job or live trading sessions eating into dev time, extend to 3 weeks.

**The absolute minimum viable Phase 1b** ("Override works + EMA works + `/health` responds") is items 3, 4, 6 (skeleton only), and a stub for items 1-2 that reads VIX from a hardcoded value or a manual input. This gets you a compute cycle that produces EMA + Zone states from real AV bars, with Override in STALE/UNKNOWN mode until IB is connected. You can ship this in **5-6 days** and add IB + Policy Engine + Tier 2 as a fast follow. This approach has a real advantage: it lets you validate the compute cycle plumbing end-to-end before adding the most complex components (Override's 7 inputs, Policy Engine's 13 rejections). I recommend this staged approach within Phase 1b: **1b-alpha** (cycle + EMA + Zone, ~1 week) → **1b-beta** (IB + Override + Policy Engine + Tier 2 + replay, ~1 week).

---

## CV-15: Top 3 Practical Implementation Risks

**Risk 1: IB Gateway operational fragility on the VPS.** This is the single most likely source of frustration. IB Gateway is a Java Swing application designed for desktop use, forced into headless mode via IBC — a third-party controller that automates GUI interactions via accessibility APIs. It is inherently brittle: daily mandatory restarts, session token expiration requiring re-authentication (sometimes with 2FA), random disconnects during IB server maintenance windows (Saturday nights, holidays), and Java memory pressure on a 4GB VPS competing with Python processes. You will spend more time debugging IB Gateway connectivity than any other component in Phase 1b. **Mitigation:** Build the system to work without IB from day one. Override runs in STALE/UNKNOWN mode, the compute cycle continues, the daily report says "Override: DEGRADED (IB offline)." This is not a fallback — it is the normal operating mode during Phase 1a and should remain graceful in Phase 1b. Accept that IB will be down 5-10% of the time and design around it.

**Risk 2: Alpha Vantage rate limit collisions and data gaps.** You have 75 requests/min, 25 tickers every 5 minutes = 25 requests per cycle. That is 5 req/min for scheduled fetches — comfortable. But add news-triggered out-of-cycle fetches (6-8/day), AV News Sentiment (every 15 min for 25 tickers = ~100 req/hour), and AV Earnings Calendar (weekly), and you are approaching the rate limit during busy periods. A 429 response from AV means missing an M5 bar — and a missing bar can cascade into a wrong EMA calculation if not handled. **Mitigation:** Implement a centralized AV rate limiter (token bucket, 75 tokens/min) shared across all AV consumers. When news-triggered fetches spike, they borrow from the next cycle's budget, and the next scheduled fetch skips tickers that were already fetched out-of-cycle. Queue AV News Sentiment fetches at lower priority than M5 bars. Log every 429 response — if you see more than 2/day, you need to restructure fetch scheduling.

**Risk 3: Manual observation data is imprecise, making replay tests frustrating.** Your Day 4/5 observations are session notes and screenshots — "Override activated around 2:20," "NVDA crossed EMA somewhere in Zone 2." These are not timestamped to the minute, let alone aligned to 5-minute boundaries. When the replay test produces Override ON at 14:15 and your notes say "around 2:20," you cannot tell if the system is wrong or the notes are imprecise. You will spend time debugging phantom mismatches that are actually observation-precision issues. **Mitigation:** Accept wide tolerances for the first replay (±15 minutes for state transitions, ±10% for scores). The replay test's primary value in Phase 1b is catching *gross* errors (Override stuck in OFF all day when you manually observed it ON, EMA showing BEAR when you saw BULL). Tighten tolerances over Phase 1c as the system itself starts producing the "expected outputs" from live operation — by Week 5, you will be comparing system-day-N outputs against system-day-N+1 outputs, not against imprecise human notes.
