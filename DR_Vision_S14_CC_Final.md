# DR Session S14-CC — System Vision Cross-Validation (Final)
# Target: Claude Code Opus 4.6
# Topic: Cross-validate System Vision v2 + ChatGPT Pro S14 (9.0/10) + S15 (9.5/10) findings
# Date: March 14, 2026
# Relationship: Final cross-validation before implementation

---

## Context

You are performing the final cross-validation of the System Vision & Architecture v2.0 for a trading research system called "Market Structure & Trading Systems." This document has been through two ChatGPT Pro reviews:

- **S14 (9.0/10):** Identified 12 key findings (score-bucket cohorting, veto analysis, rule versioning, N-count independence, VIX data gap, snapshot incoherence, etc.)
- **S15 (9.5/10):** Deep implementation review. Found 3 legacy contradictions, ib_insync archived, IB costs understated, Phase 1b overloaded, Tier 2 should not directly flip state, evidence-revision model for multi-source fusion.

All S14 findings were integrated into v2. S15 findings need integration. Your job is the final verification before we start coding.

The attached `System_Vision_Architecture_v2.md` is the current document with S14 integrated but S15 NOT yet applied.

---

## What the System Does

A **research amplification platform** for a solo developer-trader. NOT a trading bot. The system:

1. Continuously collects M5 market data (Alpha Vantage, 25 tickers) and real-time VIX/VVIX/oil (Interactive Brokers)
2. Ingests Telegram news from 3 Russian-language channels via Telethon, analyzes with Two-Tier NLP (regex + Claude API)
3. Computes framework states every 5 min: Override 3.0, EMA 9/21 Gate, 5-Zone Grid
4. Policy Engine enforces precedence hierarchy + 13 standing rejections
5. Detects patterns, tracks hypothesis N-counts, runs shadow portfolio
6. Produces daily scorecard (4-tier: integrity → calibration → research → P&L)
7. Auto-research via Trading Council (3-model LLM consensus) for detected patterns
8. All data available for human+Claude live sessions — we arrive with full day log, not reconstructed memory

### Architecture
Modular monolith. Single asyncio process + Telethon process. SQLite WAL with typed tables. Hetzner CX22 VPS (~$5/mo). systemd supervisor.

### Key S14 Decisions Already Integrated
- Score-bucket cohorting (all hard-gate trades, score as metadata)
- Config versioning (`config_versions` table, effective_from timestamps)
- Veto analysis (raw + filtered snapshot layers, post-hoc evaluation)
- N-count independence (independent episodes: day × regime × catalyst)
- Immutable compute cycles (freeze-compute-write, atomic transactions)
- Emergency micro-cycles (react_now triggers, T+5/T+15/T+30 reactions)
- IB Bridge in Phase 1b (Override 3.0 full formula from Week 3)
- Two-Tier NLP (Tier 1 regex free, Tier 2 Claude API ~$1.5/mo)
- AV News Sentiment + StockTwits as additional sources
- Earnings calendar from AV
- 4-tier daily scorecard (integrity → calibration → research → P&L)
- Silent auto-research Phase 1c (3/day, Independent N ≥ 3)
- Web dashboard Phase 2 (FastAPI + Jinja2 + Chart.js)

---

## ChatGPT Pro S15 Key Findings (to be integrated)

### Critical Fixes

**1. Three legacy contradictions in document:**
- Shadow portfolio section still says "Score ≥ 7/10" entry criterion → must be removed (score-bucket cohorting replaces it)
- Auto-research has two versions: 10/day + Telegram vs 3/day + silent. Phase 1c version (3/day silent) should be the only one
- Dashboard "no auth for read-only pages" is not acceptable → localhost bind + SSH tunnel/Tailscale + auth on all routes

**2. ib_insync is archived.** Our planned Python library for IB API is no longer maintained. Must use official `ibapi` or a thin maintained wrapper.

**3. IB market data costs understated.** CBOE Streaming Indexes + CFE Enhanced + NYMEX L1 ≈ $10/mo, not $3-5/mo. Total budget ~$85-90/mo.

**4. Phase 1b overloaded (16 components → 8 core + 3 stretch).**

### Architectural Changes

**5. Tier 2 must NOT directly flip framework state.** LLM recommends → deterministic mapper → `EventPenaltyCandidate` / `GeoStressCandidate` → Policy Engine decides. Claude's output is a recommendation, not an action.

**6. Evidence-revision model for multi-source fusion:**
```
analysis_version = 1: Telegram-only first pass (immediate)
analysis_version = 2: + AV News Sentiment (5-15 min later)
analysis_version = 3: + StockTwits (15-30 min later)
```
Don't wait for all sources. Upgrade confidence incrementally.

**7. Reaction snapshots ≠ full recomputation.** T+5/T+15/T+30 should be lightweight scheduled observations, not full engine passes. Prevents cascade.

**8. Multi-horizon veto outcomes:**
```
veto_outcome_15m: "missed_opportunity"
veto_outcome_60m: "inconclusive"
veto_outcome_eod: "correct_veto"
```
"Correct at 15m, wrong by EOD" = information about horizon sensitivity, not a bug.

**9. Two config version IDs:** `deploy_version` (code/build changes) vs `research_config_version` (strategy/runtime parameters).

**10. Tier 2 contract versioned separately.** Prompt/schema changes = analytically meaningful → `tier2_schema_version`.

### Operational

**11. IB Gateway: cap Java memory at ~1024MB.** Default 4000MB on 4GB VPS = OOM.

**12. StockTwits → Phase 2.** API stability uncertain, confirmation value weak, divergence value real but tertiary.

**13. Anthropic structured outputs for Tier 2.** Use schema-constrained responses, not prompt-only JSON.

**14. Cycle overrun handling.** Compute lock + overrun counter. If previous cycle active → skip or coalesce, never backlog.

### S15 Compute Cycle Specification (7 steps)

```
1. CONTINUOUS INGEST (always running)
   AV daemon → bars_m5
   Telethon → news_items (Tier 1 + queue Tier 2)
   IB bridge → latest VIX/VVIX/VX/CL state
   AV News Sentiment → av_news_sentiment (periodic)

2. CYCLE TRIGGER (every 5 min wall clock)
   Create cycle_id. Acquire compute lock.
   If previous cycle active → record overrun, skip.

3. FREEZE (no network calls)
   Freeze: research_config_version, latest bars, macro state,
   recent Tier 2 results, earnings, freshness metadata.

4. VALIDATE FRESHNESS
   If critical source stale → mark module degraded.
   Stale IB → Override = STALE/UNKNOWN.
   Stale earnings → earnings-sensitive entries blocked.

5. COMPUTE (fixed order)
   4H bars synthesis → EMA → Zone → Override components →
   assemble raw states → Policy Engine → filtered snapshot →
   shadow portfolio decisions → veto candidates → research candidates.

6. ATOMIC WRITE (one SQLite transaction)
   cycle metadata + module states + raw snapshot +
   filtered snapshot + shadow decisions + event log rows.

7. POST-COMMIT SIDE EFFECTS
   Telegram alerts, research queue, T+5/T+15/T+30 scheduling,
   release compute lock, write heartbeat.
```

### S15 Testing Priority
1. Golden-day replay (Day 4/5 data → verify matches manual observations)
2. Policy Engine (every rejection, precedence, earnings veto)
3. Freeze-compute-write invariants (same inputs = same outputs)
4. DST boundary tests (March 8 US, March 27 Israel)
5. News pipeline failures (timeout, 429, schema mismatch, duplicates)
6. IB reconnect / stale data
7. Performance budget (25-ticker cycle p50/p95 on VPS)

### S15 Phase 1b Revised Scope (8 core)
1. IB Gateway setup (headless + IBC + systemd)
2. Minimal IB bridge (VIX, VVIX, VX1! — Override deps only)
3. EMA state computation
4. Zone state
5. Policy Engine (precedence + 13 rejections + earnings check)
6. Immutable compute cycle skeleton
7. Tier 2 news with schema validation (structured outputs)
8. Replay test + critical tests

**Deferred from Phase 1b to Phase 2:** StockTwits, full multi-source fusion, full emergency micro-cycles, rich veto classification, DXY/breadth if not in Override, dashboard.

---

## Cross-Validation Questions

### Vision & Architecture (CV-1 to CV-3)

**CV-1: S15 7-step compute cycle.** Is this the right sequence? Any ordering dependencies missed? What about the freeze step — is reading "latest" from multiple tables in SQLite WAL guaranteed consistent without explicit snapshot isolation?

**CV-2: Evidence-revision model (analysis_version 1/2/3).** Practical implementation: three separate DB writes updating the same news_item row? Or three linked rows? How to handle Tier 2 analysis that arrives after the compute cycle already used Tier 1 data?

**CV-3: Tier 2 → deterministic mapper → Policy Engine.** S15 says LLM should recommend, not act. Concrete implementation: what does the deterministic mapper look like? Simple threshold on `event_penalty_trigger` confidence? Or rule-based classification?

### IB Integration (CV-4 to CV-6)

**CV-4: ibapi (official) vs alternatives.** ib_insync is archived. Official `ibapi` is lower-level. What's the practical difference in development effort? Is there a maintained alternative? How much wrapper code do we need?

**CV-5: IB Gateway on VPS — Java memory tuning.** S15 says cap at 1024MB. Is this sufficient for real-time streaming of VIX + VVIX + VX1! + oil? What's the minimum viable heap for our use case?

**CV-6: IB pacing rules for our use case.** We need VIX/VVIX every 5 min (or streaming), VX1! periodically, oil periodically. How does IB pacing work? Can we use streaming bars instead of polling? What are the exact rate limits?

### Implementation Details (CV-7 to CV-10)

**CV-7: SQLite WAL consistency during freeze step.** Multiple tables, one reader. Is `BEGIN IMMEDIATE` or `BEGIN DEFERRED` needed? Or is WAL snapshot isolation automatic per connection?

**CV-8: Anthropic structured outputs for Tier 2.** S15 recommends schema-constrained responses. How to implement with the current Anthropic API? JSON mode? Tool use? What's the most reliable approach for guaranteed schema compliance?

**CV-9: systemd supervision for 3 processes.** Main engine + Telethon + IB Gateway. Dependencies, ordering, restart policies, health checks. What's the right systemd configuration?

**CV-10: Python package structure.** Given Phase 1a (data + news) → 1b (intelligence + IB) → 1c (shadow + patterns), what's the optimal `src/` layout that scales to 16+ modules without refactoring?

### Validation & Testing (CV-11 to CV-13)

**CV-11: Golden-day replay test.** We have Day 4 (March 12) and Day 5 (March 13) live session data with manual observations. How to structure the replay: feed raw bars + news → run compute → compare Override/EMA/Zone states with our manual notes? What format should "expected outputs" be in?

**CV-12: Performance budget.** 25 tickers × (EMA + RSI + ADX + Squeeze) + Override (7 components) + Zone + Policy Engine + snapshot write. All from frozen SQLite reads. Target: <30 sec on Hetzner CX22 (2 vCPU, 4GB). Realistic? Where are the bottlenecks?

**CV-13: Config versioning implementation.** Two version IDs (deploy_version + research_config_version) + tier2_schema_version. How to implement cleanly? Middleware that stamps every DB write? Or explicit in each module's write method?

### Risk & Scope (CV-14 to CV-15)

**CV-14: S15 Phase 1b scope (8 core).** Is this realistic for 2 weeks? What's your estimate? Could it be tighter — what's the absolute minimum for "Override works + EMA works + bot responds /health"?

**CV-15: Top 3 risks.** From everything you've seen (v2 + S14 + S15), what are the three most likely failure modes when we start coding? Not architectural risks — practical implementation risks.

---

## Output Format

1. **S14 + S15 Integration Assessment** — are all findings correctly understood? Any misinterpretations?
2. **CV-1 through CV-15 Answers**
3. **Divergences from S15** — where you disagree with ChatGPT Pro
4. **Additional Blind Spots** — things neither we nor S14 nor S15 considered
5. **Concrete Code Patterns** — for key components (compute cycle, Policy Engine, IB bridge, Tier 2 mapper)
6. **Recommended Final Changes** to Vision v2 before coding begins

## Constraints
- Solo developer, ~$85-90/mo budget (revised)
- Python 3.10+, SQLite WAL, asyncio
- Existing infrastructure: Trading Council (FastAPI localhost:8001), AV pipeline, Telegram bot, TradingView
- Framework hierarchy non-negotiable
- 13 standing rejections non-negotiable
- "Scientific instrument, not paper trader with LLM accessories"
- Practical > elegant. Working > perfect.
