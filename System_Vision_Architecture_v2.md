# Market Structure & Trading Systems — System Vision & Architecture
# Version: 2.0
# Date: March 14, 2026
# Purpose: Specification for DR validation (ChatGPT Pro S14 + Claude Code S14-CC)

---

## 1. PHILOSOPHY

### What We're Building

This is NOT a trading bot. This is NOT an alert system. This is a **research amplification platform** — a system that makes the human-AI collaborative research process more efficient, data-rich, and verifiable.

### How We Work Today (5 Live Sessions Completed)

A human trader and Claude AI work together in real-time during US market sessions (16:30-23:00 IST). The workflow:

1. **Live Observation:** Trader shares TradingView screenshots every 30-60 minutes. Claude analyzes: EMA 9/21 structure, Override 3.0 status, VIX regime, cross-asset context, timing zones.

2. **Pattern Discovery:** Together we identify market behaviors — "Override activated at 10:15 ET and NVDA dropped 1.2% in 20 minutes", "COIN diverged from BTC for the 16th time during equity stress."

3. **Hypothesis Formation:** Observations become hypotheses with N-counts. N=1 is a hypothesis, N=5-10 gets promoted to a rule.

4. **External Validation:** Hypotheses are validated through structured Deep Research sessions with ChatGPT Pro (13 sessions), Claude Code (2 sessions), and Gemini (6 rounds). Each session is scored (X/10) and findings classified as VALIDATED/REJECTED/DEFERRED.

5. **Framework Evolution:** Validated findings update the Temporal Market Structure Framework — a growing knowledge base of rules, modules, and principles.

**Results so far:** 36 validation entries, 13 standing rejections, 16+ modules designed, Override 3.0 validated, EMA 9/21 gate validated, 5-Zone Conditional Temporal Grid validated.

### The Problem

Our bottleneck is manual data collection. The trader takes screenshots, describes what they see, Claude analyzes. We see the market "through a keyhole" — one snapshot per hour. Between snapshots, we miss Override transitions, EMA crosses, volume spikes, news catalysts. When we sit down to analyze, we reconstruct from memory.

### The Solution

A system that runs alongside our collaborative sessions, continuously collecting and computing. When we sit down to work, the full day's data is already structured, computed, and logged. We skip "what happened?" and go straight to "why did it happen?" and "what does it mean for our theory?"

### Three Evolutionary Phases

**Phase A (current):** Human + Claude = manual research. Screenshots, discussion, DR validation.

**Phase B (building now):** System runs in parallel. Collects data, computes framework states, ingests news, detects patterns, logs everything. Produces daily reports and shadow portfolio. Human + Claude sessions become richer because data is pre-collected.

**Phase C (future):** System has proven itself via shadow portfolio metrics. Graduates to semi-autonomous or autonomous operation with real capital. Human approves or system executes independently.

**Critical principle:** Phase B does NOT replace human-AI sessions. It amplifies them. The system is a data engine; interpretation and strategy remain human + Claude.

---

## 2. SYSTEM ARCHITECTURE

### Core Design: Modular Monolith (Option A+)

**Validated by:** ChatGPT Pro S13 (9.2/10) + Claude Code S13-CC (9.2/10). Both independently recommended modular monolith. Microservices rejected (operational tax for solo dev). Pure Skills rejected (no persistence/daemon). Serverless rejected (cold start latency, no persistent connections).

### Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│              DATA LAYER (continuous)             │
│                                                 │
│  Alpha Vantage    Telethon         (future)     │
│  M5 Fetcher  ──→  News Ingest  ──→ IB/Deribit  │
│  25 tickers       3 TG channels    VIX/DVOL    │
│  every 5 min      real-time        oil/DXY     │
│       │                │                        │
│       ▼                ▼                        │
│  ┌─────────── SQLite WAL ──────────────┐       │
│  │ bars_m5 │ news_items │ event_log    │       │
│  │ override_state │ ema_state │ zone   │       │
│  │ positions │ research_log │ ...      │       │
│  └─────────────────────────────────────┘       │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│           COMPUTATION LAYER (every 5 min)        │
│                                                  │
│  EMA 9/21 Gate ──→ Override 3.0 ──→ Zone Grid   │
│  (4H + M5)         (VIX z-score)    (5 zones)   │
│       │                │                │        │
│       ▼                ▼                ▼        │
│         Policy Engine (precedence + rejections)  │
│              GeoStress > Override > EMA > Zone    │
│                        │                         │
│                        ▼                         │
│              Filtered State Snapshot              │
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│           PATTERN DETECTION LAYER                 │
│                                                   │
│  Anomaly Detector ──→ N-Count Tracker            │
│  • Override frequency anomalies                   │
│  • Cross-asset divergences (COIN, IBIT, ETHA)   │
│  • Volume spikes in unusual zones                │
│  • News ↔ price reaction correlation             │
│  • EMA cross clustering                          │
│  • Hypothesis promotion candidates (N→threshold) │
│                        │                          │
│              ┌─────────┴──────────┐              │
│              ▼                    ▼              │
│     ┌──────────────┐   ┌─────────────────┐      │
│     │ Auto-Research │   │ Shadow Portfolio │      │
│     │ Council API   │   │ Virtual trades  │      │
│     │ Mini-DR runs  │   │ Daily scorecard │      │
│     └──────┬───────┘   └────────┬────────┘      │
│            │                     │               │
└────────────┼─────────────────────┼───────────────┘
             │                     │
┌────────────▼─────────────────────▼───────────────┐
│              OUTPUT LAYER                         │
│                                                   │
│  Telegram Bot                                     │
│  ├── Daily Report (state transitions, news,       │
│  │   correlations, shadow scorecard)              │
│  ├── Pattern Alerts ("COIN divergence N=17,       │
│  │   auto-analysis: consistent with stress")      │
│  ├── Research Queue ("DR prompt ready for         │
│  │   [topic]. Data attached. Send?")              │
│  └── System Health (/health, /status)             │
│                                                   │
│  Research Log (for human+Claude sessions)         │
│  ├── Full day replay data                         │
│  ├── Pre-computed state transitions               │
│  ├── News ↔ price reaction pairs                  │
│  └── Auto-research results from Council           │
└───────────────────────────────────────────────────┘
             │
┌────────────▼─────────────────────────────────────┐
│         HUMAN + CLAUDE SESSIONS                   │
│                                                   │
│  We arrive with:                                  │
│  • Complete day log (not reconstructed memory)    │
│  • All Override/EMA/Zone transitions timestamped  │
│  • News events correlated with price reactions    │
│  • Shadow portfolio performance                   │
│  • Auto-research results to review                │
│  • Pattern detector findings to discuss           │
│                                                   │
│  We focus on: WHY, not WHAT                       │
│  We update: rules, parameters, new hypotheses     │
│  System applies updates immediately               │
└───────────────────────────────────────────────────┘
```

### Technical Stack

| Component | Technology | Status |
|-----------|-----------|--------|
| Runtime | Python 3.10+, single asyncio process (Phase 1), +Telethon process (Phase 1a) | To build |
| Persistence | SQLite WAL, typed tables per module | To build |
| Scheduling | asyncio periodic tasks (no APScheduler) | To build |
| User Telegram | python-telegram-bot (PTB), single bot | Existing (extend) |
| News Ingestion | Telethon — Python library for Telegram API (MTProto protocol). Connects as user account to read channel messages. Unlike a regular Telegram bot (PTB), can monitor any public/subscribed channel without admin access. 3 channels monitored. | To build |
| Trading Council | FastAPI localhost:8001, Claude+GPT+Gemini consensus | Existing, production |
| Data Pipeline | Alpha Vantage Premium, 25 tickers M5 | Existing (move from GH Actions to daemon) |
| VPS | Hetzner CX22 (~$5/mo), 2 vCPU, 4GB RAM | To provision |
| Supervisor | systemd (2 service units) | To configure |

### Key Architectural Decisions (from S13 + S13-CC)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Modular monolith (A+) | Solo dev, $70/mo budget, 16+ modules |
| State management | SQLite WAL, typed tables | Queryable, debuggable, zero ops overhead |
| Module communication | In-process calls + DB state | No message broker, no HTTP between modules |
| Scheduling | asyncio `run_periodic()` | 20 lines replaces APScheduler dependency |
| Policy Engine placement | Before snapshot assembly | Council never sees suppressed signals |
| Telegram bot | One PTB bot for all user I/O | Single UX surface |
| News ingestion | Telethon (Python Telegram client library, MTProto) — separate process | Reads subscribed channels as user account; regular bots can't monitor channels without admin. Pyrogram (alternative library) unmaintained |
| Council role | Advisory only, cannot override hard blocks | Deterministic rules > LLM opinions |
| Deployment | VPS from Phase 1a | 24/7 availability for Telegram + data collection |

---

## 3. DATA ARCHITECTURE

### Data Sources (Priority Order)

**Priority 1 — Market Data (Phase 1a):**
- Alpha Vantage Premium: 25 equities + BTC/ETH M5 OHLCV, 75 req/min limit
- Daemon-based polling every 5 min during market hours (16:30-23:00 IST)
- Computed locally: EMA 9/21, RSI, ADX, Squeeze, volume metrics

**Priority 1 — Telegram News (Phase 1a, elevated from Phase 2):**
**Priority 1 — News & Market Intelligence (Phase 1a):**
- Telegram channels (3 channels via Telethon): 1 primary (~90%), 2 secondary. ~10 msg/hour, Russian. Tier 1 regex + Tier 2 Claude API analysis. Primary intelligence source.
- Alpha Vantage News Sentiment API (already available, zero extra cost): Structured sentiment data per ticker. `GET /query?function=NEWS_SENTIMENT&tickers=NVDA,TSLA,BTC`. Returns: title, summary, source, sentiment_score (-1 to 1), relevance_score, tickers. Used for cross-verification: Telegram says NVDA bullish → AV Sentiment confirms with 3 articles scored 0.8 → higher confidence.

**Priority 1 — Market Data (Phase 1a):**
- Alpha Vantage Premium: 25 equities + BTC/ETH M5 OHLCV, 75 req/min. Daemon polling every 5 min.
- Event-driven: news mention of ticker → immediate M5 refresh for that ticker

**Priority 2 — Derived Intelligence + Enrichment (Phase 1b):**
- Interactive Brokers: VIX, VVIX, VX futures, oil (CL), DXY, market breadth (via IB Gateway on VPS)
- Override 3.0 FULL (all 7 components, powered by IB data)
- EMA 9/21 Gate (4H synthetic from M5 bars, TrendStateScore)
- 5-Zone Conditional Temporal Grid
- Cross-asset context (BTC/ETH correlation, COIN divergence)
- **StockTwits Sentiment (free API, existing account with curated watchlist):** Aggregate sentiment (% bullish/bearish), message volume spikes, sentiment shifts per ticker. Fetched every 15-30 min (within 200 req/hr rate limit). Not a news source — a crowd mood gauge. Use cases: (a) contrarian signal when extreme sentiment, (b) retail attention spike = volatility incoming, (c) sentiment divergence vs our framework = alert. Stored in `sentiment_scores` table. Enriches Tier 2 Claude analysis: "Telegram bullish + AV Sentiment 0.8 + StockTwits 73% bullish → triple confirmation."

**Priority 3 — Future Sources (Phase 2+):**
- Deribit: DVOL, ETHDVOL, funding rates, OI
- Alpha Vantage Earnings Calendar: Weekly fetch, full CSV with estimate/actual/surprise
- Yahoo Finance RSS: Backup news source for broader coverage
- **Polymarket (free API):** Real-time prediction market probabilities for macro events (Fed rate cuts, CPI surprises, elections). Enables continuous EventPenalty scoring — instead of binary "CPI day = quarantine," use market-implied probability: "CPI surprise probability = 34% → EventPenalty = 0.34." More nuanced than any news source because it reflects actual money-weighted consensus.

### Multi-Source Intelligence Fusion

The system combines multiple sources for higher-confidence signals:

```
Telegram (human-curated, fastest)
    + AV News Sentiment (structured, AI-scored)
        + StockTwits (crowd sentiment, contrarian)
            → Tier 2 Claude API receives ALL sources
            → Structured JSON with cross-verified confidence

Example:
    Telegram: "NVDA guidance raised" (urgency: high)
    AV Sentiment: 3 articles, avg score 0.82
    StockTwits: NVDA 78% bullish, volume 3.2x average
    → Tier 2: impact_probability: 0.91, confidence: 0.88 (triple-confirmed)

Counter-example (higher value):
    Telegram: "NVDA guidance raised" (urgency: high)
    StockTwits: NVDA sentiment DROPPING (was 72%, now 58%)
    → Tier 2: impact_probability: 0.65, confidence: 0.60
    → Flag: "Retail divergence — news bullish but crowd selling. Investigate."
```

### News-Triggered Data Refresh

```
Telethon receives message from channel
    → extract tickers mentioned (regex + keyword dictionary)
    → if ticker in watchlist:
        1. Write to news_items table
        2. Emit event: NEWS_TICKER_MENTION
        3. AV fetcher: immediate out-of-cycle fetch for this ticker
        4. Snapshot: record "pre-news state" and "post-news state" (5 min later)
        5. Log news↔price reaction pair in event_log
```

This creates a dataset of news→reaction pairs that we can analyze in our sessions.

### SQLite Schema

Typed tables per module (not generic JSON blobs). Full schema in ADR v1 §2. Key tables:

| Table | Purpose | Phase |
|-------|---------|-------|
| `bars_m5` | M5 OHLCV cache, validated on ingestion | 1a |
| `news_items` | Telegram channel messages, parsed and scored (Tier 1 + Tier 2) | 1a |
| `av_news_sentiment` | Alpha Vantage News Sentiment API results per ticker | 1a |
| `event_log` | Append-only audit trail of everything | 1a |
| `config_versions` | Rule versioning with effective_from timestamps | 1a |
| `earnings_calendar` | AV Earnings Calendar: ticker, date, estimate, actual, surprise | 1a |
| `ema_state` | Per-ticker EMA gate state (typed columns) | 1b |
| `override_state` | Override 3.0 state machine (typed columns) | 1b |
| `zone_state` | Current temporal zone | 1b |
| `sentiment_scores` | StockTwits aggregate sentiment per ticker (% bullish, volume, shift) | 1b |
| `snapshots` | Immutable compute cycle snapshots (raw + filtered layers, veto analysis) | 1b |
| `positions` | Shadow portfolio entries/exits (tagged with config_version, score bucket) | 1c |
| `hypothesis_tracker` | N-count with independent episode tracking | 1c |
| `research_log` | Auto-research results from Council | 1c |
| `pattern_log` | Detected anomalies and divergences | 1c |

---

## 4. NEWS INTELLIGENCE MODULE (#15)

### Architecture — Two-Tier NLP Pipeline

The news pipeline uses two tiers: fast deterministic filtering (Tier 1) followed by LLM-powered deep analysis for relevant messages (Tier 2). This approach keeps costs low (~$1.5/mo) while providing structured intelligence that integrates directly with Override 3.0 and the Policy Engine.

```
Telethon Client (Python Telegram API library — connects as user account, not bot)
    Runs as separate process under systemd. Unlike PTB bot, can read any
    public/subscribed channel without admin privileges.
    │
    ├── Channel 1 (primary, ~90% volume)
    ├── Channel 2 (secondary)
    └── Channel 3 (secondary)
    │
    ▼
Message Handler:
    1. Extract raw text (ignore images in Phase 1)
    2. Language: Russian (fixed, no detection needed)
    3. Handle forwarded messages (extract original text)
    4. Handle edited messages (update existing news_item)
    │
    ▼
TIER 1 — Deterministic Filter (every message, zero cost):
    1. Normalize text (lowercase, strip URLs, preserve $tickers)
    2. Ticker extraction: regex for $NVDA, NVDA, "Nvidia" + alias dictionary
    3. Sentiment keywords: "рост", "падение", "обвал", "ралли", etc.
    4. Urgency keywords: "СРОЧНО", "BREAKING", "только что"
    5. Relevance score: (watchlist_tickers × 2) + (sentiment × 1) + (urgency × 1.5)
    │
    ├── relevance < threshold → log as "low_relevance", no further action
    │
    ▼ relevance ≥ threshold (~10-15 messages/day pass)
    │
TIER 2 — Claude API Deep Analysis (~$0.003-0.005 per call):
    Send message text + current market context to Claude Sonnet API.
    Structured JSON response:
    │
    │   {
    │     "impact_probability": 0.85,         // 0-1, likelihood of >0.5% move
    │     "direction": "bullish",             // bullish / bearish / neutral / mixed
    │     "primary_tickers": ["NVDA", "AMD"], // directly affected
    │     "secondary_tickers": ["SMCI", "QQQ"], // indirectly affected
    │     "urgency": "react_now",             // react_now / monitor / background
    │     "category": "earnings",             // macro_fed / macro_data / earnings /
    │                                         // geopolitical / crypto / sector / corporate
    │     "override_relevance": "high",       // high / medium / low / none
    │     "event_penalty_trigger": false,      // true = auto-activate EventPenalty
    │     "geostress_signal": false,          // true = potential GeoStress component
    │     "summary_en": "NVDA beat Q4 estimates...", // English summary for logs
    │     "confidence": 0.82                  // model's self-assessed confidence
    │   }
    │
    ▼
Actions (based on Tier 2 output):
    1. Write enriched news_item to DB (raw text + Tier 1 scores + Tier 2 analysis)
    2. if primary_tickers in watchlist → immediate out-of-cycle M5 fetch
    3. if event_penalty_trigger = true → auto-activate EventPenalty in Override 3.0
    4. if geostress_signal = true → increment GeoStress component counter
    5. Record pre-news market state snapshot
    6. Schedule post-news snapshots at T+5, T+15, T+30 min (multi-window, per S14)
    7. if urgency = "react_now" → Telegram alert to trader
    8. Log news↔price reaction pair in event_log for session analysis
```

### Why Two Tiers

| Aspect | Tier 1 Only (original plan) | Tier 1 + Tier 2 (updated) |
|--------|---------------------------|--------------------------|
| Cost | $0 | ~$1.5/mo (10-15 Claude calls/day) |
| Ticker extraction | Good (regex + aliases) | Same (Tier 1 handles this) |
| Sentiment accuracy | ~65-70% (keywords) | ~85-90% (Claude understands context) |
| Event classification | Manual keyword lists | Automatic (Claude knows FOMC = event day) |
| Override integration | None | Direct (event_penalty_trigger, geostress_signal) |
| Multilingual handling | Keyword lists per language | Native (Claude reads Russian fluently) |
| Structured output | Basic (relevant/not) | Rich JSON → direct DB integration |

### Claude API Prompt Template (Tier 2)

```python
TIER2_SYSTEM_PROMPT = """You are a financial news analyst for a trading system.
Analyze the Telegram channel message below. The trader monitors US equities
(NVDA, META, TSLA, GOOGL, AAPL, AMZN, MSFT, BA, CRWD, PLTR),
crypto (BTC, ETH, IBIT, ETHA, COIN, MARA, MSTR),
China ADRs (BABA, BIDU, TCEHY, KWEB),
and macro indicators (VIX, oil, gold, DXY, Fed policy).

Current market context:
- VIX: {vix_level} ({vix_change}%)
- Override state: {override_state}
- Current zone: {zone_name} ({zone_time} ET)
- Market hours: {market_status}

Return ONLY a JSON object with these fields:
impact_probability, direction, primary_tickers, secondary_tickers,
urgency, category, override_relevance, event_penalty_trigger,
geostress_signal, summary_en, confidence

No preamble, no markdown, no explanation — pure JSON only."""

TIER2_USER_PROMPT = """Telegram message ({channel_name}):
{message_text}"""
```

### Cost Model

| Metric | Value |
|--------|-------|
| Tier 1 messages/day | ~80-100 (all channels) |
| Pass to Tier 2 | ~10-15/day (relevance ≥ threshold) |
| Claude Sonnet per call | ~$0.003-0.005 (short input + JSON output) |
| Daily Tier 2 cost | ~$0.03-0.075 |
| Monthly Tier 2 cost | **~$1-2/mo** |
| Uses same API key as Council | Yes (Anthropic key already configured) |

### Ticker Alias Dictionary (Russian)

```python
TICKER_ALIASES_RU = {
    'nvidia': 'NVDA', 'нвидиа': 'NVDA', 'нвидия': 'NVDA',
    'тесла': 'TSLA', 'tesla': 'TSLA',
    'мета': 'META', 'фейсбук': 'META',
    'биткоин': 'BTC', 'биток': 'BTC', 'btc': 'BTC',
    'эфир': 'ETH', 'эфириум': 'ETH', 'eth': 'ETH',
    'coinbase': 'COIN', 'коинбейс': 'COIN',
    'палантир': 'PLTR', 'palantir': 'PLTR',
    'alibaba': 'BABA', 'алибаба': 'BABA',
    'tencent': 'TCEHY', 'тенсент': 'TCEHY',
    'baidu': 'BIDU', 'байду': 'BIDU',
    'crowdstrike': 'CRWD',
    'apple': 'AAPL', 'эпл': 'AAPL',
    'google': 'GOOGL', 'гугл': 'GOOGL',
    'amazon': 'AMZN', 'амазон': 'AMZN',
    'vix': 'VIX', 'викс': 'VIX',
    'нефть': 'OIL', 'oil': 'OIL',
    'золото': 'GOLD', 'gold': 'GOLD',
    'доллар': 'DXY', 'dxy': 'DXY',
    'фед': 'FED', 'fed': 'FED', 'фрс': 'FED',
    # ... extend as needed
}
```

### Integration with Main System

News items enrich the computation layer in three ways:

1. **Immediate (Tier 2 triggers):**
   - News about NVDA → out-of-cycle M5 fetch → pre/post snapshot
   - `event_penalty_trigger: true` → Override EventPenalty auto-activated
   - `geostress_signal: true` → GeoStress component counter incremented
   - `urgency: react_now` → Telegram alert to trader

2. **Periodic (every 5-min cycle):**
   - Recent news_items included in MarketSnapshot context
   - Council receives news context for enriched analysis
   - Pattern Detector correlates news events with price reactions

3. **Session replay (for human+Claude analysis):**
   - All news events timestamped and linked to market state
   - News↔price reaction pairs pre-computed (T+5, T+15, T+30)
   - Tier 2 analysis available as structured data for review

---

## 5. PATTERN DETECTION & AUTO-RESEARCH

### What Pattern Detector Watches

| Pattern | Trigger | Action |
|---------|---------|--------|
| Override frequency anomaly | >3 transitions/day | Log + alert |
| Cross-asset divergence | COIN vs BTC > 2σ | Log + auto-research if N threshold approaching |
| Volume spike in unusual zone | Volume > 2x median in Dead Zone | Log + news correlation check |
| EMA cross clustering | 3+ tickers cross same direction within 1 hour | Log + sector rotation analysis |
| News→price reaction | High-relevance news + >0.5% move within 15 min | Log reaction pair for session analysis |
| Hypothesis promotion | N-count reaches threshold (e.g., N=10) | Alert: "COIN divergence N=17, ready for Directional Reasoning validation" |
| Framework rule violation | Shadow trade contradicts standing rejection | Alert: system error, rule not enforced |
| Streak detection | Same asset GO signal 3+ consecutive days | Log + Council mini-analysis |

### Auto-Research via Council

When Pattern Detector identifies a significant finding:

```python
# Lightweight research — uses existing Council infrastructure
async def auto_research(pattern: PatternDetection):
    snapshot = build_research_snapshot(pattern)
    # Use existing Council endpoint with AUTO_RESEARCH trigger
    result = await council_client.analyze(
        trigger_type="AUTO_RESEARCH",
        snapshot=snapshot,
        question=pattern.research_question
    )
    # Store result
    await db.insert_research_log(pattern, result)
    # Notify via Telegram
    await telegram.send(f"Auto-analysis: {pattern.summary}\n"
                        f"Council ({result.consensus}): {result.reasoning[:200]}")
```

Cost: same as regular Council call (~$0.012). Budget: max 10 auto-research calls/day ($0.12/day).

### Research Queue for Full DR Sessions

For findings that need deeper analysis than Council can provide:

```
Pattern Detector: "Override 3.0 failed to predict VIX spike at 14:22.
    VIX z-score was -0.3 (below threshold) but VIX jumped 8% in 15 min.
    Possible blind spot in Override formula."

    → System generates DR prompt automatically:
    "Context: [framework state at 14:22, VIX data, Override parameters]
     Question: Is the Override 3.0 z-score window (15 min) too narrow?
     Should we add a 5-min micro-window for rapid spikes?"

    → Telegram: "DR prompt ready: Override rapid spike blind spot.
     Data for March 14 attached. Send to ChatGPT Pro? [Y/N]"

    → If approved: system sends via OpenAI API (key already in Council)
    → Result stored in research_log
    → Available for next human+Claude session
```

---

## 6. SHADOW PORTFOLIO

### Purpose

Quantitative validation of our framework. Not a trading strategy — a scorecard for our theories.

### Logic

```
Every 5-min computation cycle:
    for each ticker in watchlist:
        score = PolicyEngine.evaluate(ticker_state)

        if score ≥ ENTRY_THRESHOLD and no open shadow position:
            → VIRTUAL_ENTRY (log all framework states)

        if open shadow position:
            if exit_signal(ticker_state):
                → VIRTUAL_EXIT (log exit reason, P&L, duration)
            else:
                → update position_snapshot (unrealized P&L)
```

### Entry Criteria (from framework)

- 4H EMA Gate: BULL (cross UP confirmed, TSS ≥ 0.6)
- Override 3.0: OFF (timing zones reliable)
- Zone: 1 (Opening) or 4 (Breakdown) — high reliability zones
- M5 sub-state: RESUME or BREAK (not PULLBACK or REJECT)
- No standing rejections violated
- No earnings within 3 days
- Score ≥ 7/10

### Exit Criteria (from framework, still "horse race" — system tests all)

- EMA 9 rejection on M5
- Override activation (ON or WARNING)
- Zone transition to Dead Zone
- VIX spike > 2σ
- 4H EMA cross reversal
- ATR-based trailing stop (1.5 ATR from entry)
- Time-based: no exit signal after 2 hours → close at next zone transition

### Daily Scorecard (Telegram)

```
📊 Shadow Portfolio — March 14, 2026

Entries: 3 | Exits: 2 | Open: 1
Win rate: 2/3 (67%)
Total P&L: +1.05%

✅ NVDA long 181.50→183.20 (+0.94%) | 47 min | Exit: Zone 3
❌ META long 612→608 (-0.65%) | 22 min | Exit: Override ON
🔄 ETH long 2840 (open) | +1.76% unrealized

Framework accuracy:
  Override signals: 4/4 correct
  EMA Gate: 3/4 correct (META false positive)
  Zone predictions: 5/5 correct
  News correlation: 2/2 (NVDA rally post-earnings-beat news)

Hypothesis updates:
  COIN divergence: N=17 (was 16)
  Dead Zone equity compression: N=3 (was 2)

⚠️ Research queue: 1 item pending
  "Override rapid spike — 14:22 anomaly"
```

---

## 7. BUILD ORDER

### Phase 1a — Data + News Foundation (Week 1-2)

**Goal:** System collects M5 bars and Telegram news 24/7. Daily report: "X bars collected, Y news items parsed."

| # | Component | Details |
|---|-----------|---------|
| 1 | Project scaffold | `pyproject.toml`, src layout, pytest, `.env` |
| 2 | SQLite schema v1 | `bars_m5`, `news_items`, `event_log`, `schema_meta`, `heartbeats` |
| 3 | AV intraday fetcher | Async daemon, 5-min cycle, 25 tickers, bar validation |
| 4 | Telegram news ingestion | Telethon library (Python Telegram client) — 3 channels, text extraction, keyword/ticker matching |
| 5 | **AV News Sentiment** | Periodic fetch (every 15 min) for watchlist tickers → `av_news_sentiment` table. Cross-verification source |
| 6 | News-triggered refresh | Ticker mention → immediate out-of-cycle M5 fetch |
| 7 | **Config versioning** | `config_versions` table, all parameters versioned with effective_from timestamps |
| 8 | **Earnings calendar** | AV EARNINGS_CALENDAR weekly fetch → `earnings_calendar` table (ticker, date, estimate, actual, surprise) |
| 9 | Basic Telegram bot | `/health`, `/status`, daily collection report |
| 10 | systemd units | `market-engine.service` + `market-ingest.service` |
| 11 | Tests | Bar validation, ticker extraction (RU aliases), DB writes, config versioning |
| 12 | Deploy to VPS | Verify bars flowing + news ingesting |

**Milestone:** Telegram daily report: "25/25 tickers, 847 bars, 43 news items (12 Tier 2 analyzed), 156 AV sentiment entries. System uptime: 99.8%."

### Phase 1b — Intelligence Layer (Week 3-4)

**Goal:** System computes EMA/Override/Zone, correlates with multi-source intelligence. Daily report: state transitions + news→price reactions + sentiment context.

| # | Component | Details |
|---|-----------|---------|
| 1 | **IB Gateway setup** | Headless IB Gateway on VPS + IBC controller + systemd unit |
| 2 | **IB data bridge** | VIX, VVIX, VX1! (futures), oil (CL), DXY via ib_insync |
| 3 | **Override 3.0 FULL** | All 7 components: z(dVIX), z(dVVIX), TermStructure, Breadth, OilCatalyst, EventPenalty, GeoPenalty × fatigue |
| 4 | EMA 9/21 computation | 4H synthetic from M5 bars, TrendStateScore, store in `ema_state` |
| 5 | Session Timer + Zone Grid | 5-zone detection, DST handling, store in `zone_state` |
| 6 | Policy Engine | Precedence + 13 rejections + earnings proximity check |
| 7 | **Immutable compute cycles** | Freeze-compute-write pattern, cycle_id per snapshot, atomic DB transactions |
| 8 | **Snapshots with veto analysis** | Raw + filtered layers, blocked_by tracking, post-hoc veto_outcome |
| 9 | **Tier 2 news analysis** | Claude API for high-relevance messages → structured JSON → auto EventPenalty/GeoStress |
| 10 | **Emergency micro-cycles** | Triggered by urgency=react_now or VIX spike >2σ. T+5, T+15, T+30 reaction snapshots |
| 11 | **StockTwits sentiment** | Fetch every 15-30 min for watchlist tickers → `sentiment_scores` table. Crowd mood gauge |
| 12 | **Multi-source intelligence fusion** | Telegram + AV Sentiment + StockTwits → combined confidence in Tier 2 Claude analysis |
| 13 | News↔price correlation | Multi-window reaction logging (T+5, T+15, T+30) |
| 14 | Expanded daily report | State transitions, EMA crosses, news correlations, Override lifecycle, sentiment context |
| 15 | Replay test | Feed Day 4/5 data → verify matches manual observations |
| 16 | Tests | Override state machine, Policy Engine, DST edge cases, IB reconnect, veto analysis |

**Milestone:** Daily report shows all Override transitions, EMA crosses, and news→reaction pairs. Matches what we observed manually in sessions.

### Phase 1c — Analysis + Shadow (Week 5-6)

**Goal:** Pattern detection, shadow portfolio, auto-research. System produces actionable intelligence for our sessions.

| # | Component | Details |
|---|-----------|---------|
| 1 | Pattern Detector | Anomalies, divergences, streaks, near-miss detection. 4-5 high-value types only (Phase 1c) |
| 2 | **Hypothesis Tracker** | N-count with independent episode tracking (day × regime × catalyst). Auto-promotion alerts |
| 3 | **Shadow Portfolio (score-bucket)** | ALL hard-gate-passing setups entered. Score as metadata, NOT threshold. Parallel bucket analysis (5+/6+/7+/8+) |
| 4 | **Veto analysis** | Post-hoc evaluation of vetoed setups. Correct veto / missed opportunity / inconclusive |
| 5 | **Silent auto-research** | Council API, max 3/day, only Independent N ≥ 3 + confidence HIGH. Results → research_log, NOT Telegram |
| 6 | Research Queue | DR prompt generation for deep findings, manual approval via Telegram |
| 7 | **Daily Scorecard (4-tier)** | Order: (1) System Integrity → (2) Framework Calibration → (3) Research Findings → (4) Shadow P&L by score bucket |
| 8 | Council cost tracking | Daily counter + budget cap (30 regular + 3 auto-research + 15 Tier 2 news) |
| 9 | Integration tests | End-to-end: data→compute→detect→veto→report |

**Milestone:** Full 4-tier daily scorecard. Shadow portfolio with score-bucket analysis. Veto accuracy tracked. Silent auto-research producing findings for our sessions.

### Phase 2 — Enrichment (Week 7-10)

| # | Component |
|---|-----------|
| 1 | Morning Outlook (auto-generated, 10:30 IST) |
| 2 | Interactive commands (`/assess`, `/log`, `/close`) |
| 3 | Position Intelligence Mode 1 (GO/WAIT/AVOID) |
| 4 | Cross-asset divergence module (IBIT, ETHA, COIN) |
| 5 | TWAP pattern scanner |
| 6 | Research auto-send (approved via Telegram, sent via API) |
| 7 | **Web Dashboard (FastAPI + Jinja2 + Chart.js)** |

**Web Dashboard — Phase 2 Scope:**

Lightweight read-only dashboard on the same VPS, same Python process. No React, no frontend build — server-side rendered HTML with Chart.js via CDN. Zero additional infrastructure cost.

```
http://vps-ip:8080/

├── /dashboard          — live status: Override, EMA states, zone, VIX,
│                         open shadow positions, system health
├── /override           — Override transitions timeline (interactive chart)
├── /scorecard          — daily scorecard history (table, filterable by date)
├── /scorecard/:date    — detailed scorecard for specific day
├── /veto               — veto analysis table: all vetoed setups,
│                         correct/missed/inconclusive, filterable
├── /shadow             — shadow portfolio: score-bucket breakdown,
│                         P&L curve, config version comparison
├── /news               — news feed with Tier 1 + Tier 2 results,
│                         reaction pairs (T+5/T+15/T+30)
├── /sentiment          — StockTwits + AV Sentiment overview per ticker
├── /hypotheses         — hypothesis tracker: raw N, independent N,
│                         promotion status, evidence timeline
├── /config             — current config version, parameter values,
│                         version history, parameter editor (auth required)
├── /debug/snapshot/:id — raw snapshot inspector (raw + filtered layers)
├── /debug/cycle/:id    — full compute cycle: frozen inputs, results, timing
└── /debug/events       — event log browser with filters
```

**Design principles:**
- Read-only by default. Config editing requires basic auth (single user)
- Same SQLite DB — dashboard reads, engine writes. No data duplication
- Progressive: start with `/dashboard` + `/override` + `/scorecard`, add pages as needed
- Mobile-friendly (responsive CSS) — check dashboard from phone browser when Telegram isn't enough
- No authentication for read-only pages (VPS is private, not public-facing)

**Why NOT earlier:**
- Phase 1a-1b: Telegram + raw SQL sufficient for debugging
- Phase 1c: add `/debug/snapshot/:id` JSON endpoint for troubleshooting (no HTML, just API)
- Phase 2: HTML dashboard when historical analysis in Telegram becomes painful

**Trigger for building dashboard:** When you find yourself running `sqlite3` queries more than 3 times per session to answer questions Telegram can't show.

### Phase 3 — Advanced Data + Autonomy (Week 11+)

| # | Component |
|---|-----------|
| 1 | Deribit integration (DVOL, ETHDVOL, funding, OI → CryptoOverride) |
| 2 | GeoStress kill-switch (full 6-component formula) |
| 3 | Polymarket API (continuous EventPenalty scoring) |
| 4 | Yahoo Finance RSS (backup news source) |
| 5 | Shadow → execution-modeled paper trading (realistic fills) |
| 6 | Semi-autonomous mode (system proposes, human confirms) |
| 7 | Autonomous mode (system executes with risk limits) |

---

## 8. INTEGRATION PRINCIPLES

### Every Module Must:

1. **Write to its own typed state table** — not a generic JSON blob
2. **Append to event_log** — every state change, every computation
3. **Respect Policy Engine** — no module bypasses precedence or standing rejections
4. **Include freshness metadata** — `asof_utc`, `ttl_sec`, `source`, `quality_flag`
5. **Handle degradation gracefully** — if data source is down, report stale, don't crash
6. **Be toggleable** — enabled/disabled/passive/active via config table
7. **Be testable independently** — unit test with known inputs → expected outputs

### News Integration Pattern

Any future data source follows the same pattern as Telegram news:
1. Ingest raw data → write to source table
2. Extract tickers/relevance → match against watchlist
3. If high relevance → trigger out-of-cycle refresh for affected tickers
4. Record pre/post state snapshot → log reaction pair
5. Include in next computation cycle's context

This pattern applies to: Telegram channels, Deribit events, IB market data, future RSS feeds, future X/Twitter monitoring.

---

## 9. COST MODEL

| Item | Current | With System |
|------|---------|-------------|
| Alpha Vantage Premium | $50/mo | $50/mo |
| TradingView CGIF + CFE | $6/mo | $6/mo |
| **IB Market Data (Phase 1b)** | $0 | **~$3-5/mo** (CBOE One + commodity data) |
| LLM Council (regular) | ~$3.6/mo | ~$5.4/mo (30 calls/day cap) |
| LLM Council (auto-research) | $0 | ~$3.6/mo (10 calls/day cap) |
| **News Tier 2 (Claude API)** | $0 | **~$1.5/mo** (10-15 calls/day) |
| VPS (Hetzner CX22) | $0 | $5/mo |
| **Total** | **~$60/mo** | **~$75-80/mo** |

Slightly above original $70/mo ceiling, but IB Bridge eliminates VIX data gap and enables full Override 3.0 + GeoStress. The ~$5-10 increase is justified by data quality upgrade. Potential offset: evaluate if TradingView CGIF ($6/mo) can be dropped once IB provides real-time VIX.

---

## 10. SUCCESS METRICS

### Phase 1a (Week 2)
- [ ] 25/25 tickers fetched every 5 min during market hours
- [ ] 3/3 Telegram channels ingested, news_items table populated
- [ ] Daily report delivered to Telegram automatically
- [ ] VPS uptime > 99%

### Phase 1b (Week 4)
- [ ] Override state transitions match manual observations (replay test)
- [ ] EMA crosses detected and timestamped correctly
- [ ] News→price reaction pairs logged
- [ ] DST handling verified (March 27 transition)

### Phase 1c (Week 6)
- [ ] Shadow portfolio produces daily scorecard
- [ ] Auto-research generates at least 1 meaningful finding per week
- [ ] Pattern Detector identifies anomalies we didn't see manually
- [ ] Framework accuracy metrics available (Override accuracy %, EMA accuracy %)

### Phase B Complete (Week 10)
- [ ] Our live sessions are measurably more productive (less time on "what happened?")
- [ ] Shadow portfolio has 20+ trading days of data
- [ ] At least 3 framework improvements originated from system-detected patterns
- [ ] N-count tracking automated for all active hypotheses

---

## 11. QUESTIONS FOR DR VALIDATION

### For ChatGPT Pro S14:

1. **Philosophy validation:** Is "research amplification platform" the right framing? Or should we optimize for a different primary use case?

2. **News-triggered refresh:** When Telegram news mentions a ticker, we immediately fetch fresh M5 data. Is this the right reaction? Should we also adjust Override/EMA computation, or just log the raw reaction?

3. **Shadow portfolio entry criteria:** We use Score ≥ 7/10 as entry threshold. Is this reasonable? Too conservative? Too aggressive? What scoring methodology is best for validating a discretionary framework?

4. **Auto-research scope:** System uses Council (3 models) for quick analysis of detected patterns. When should it escalate to full DR (ChatGPT Pro Deep Research / Claude Code)? What's the right threshold?

5. **News NLP for Russian financial Telegram:** Regex + keyword matching for 3 channels, ~10 msg/hour. Is this sufficient? What false positive rate should we expect? What improvements would you prioritize if accuracy is below 70%?

6. **Pattern Detector design:** We listed 8 pattern types. Which are highest value? Which should be Phase 1 vs deferred? Are there patterns we're missing?

7. **Daily scorecard design:** Is our proposed format useful for improving the framework? What metrics would you add?

8. **Phase C readiness criteria:** At what point is shadow portfolio data sufficient to consider real capital? What statistical thresholds (win rate, Sharpe, max drawdown, number of trades)?

9. **Telegram as sole UI:** We're building proactive-first (system reports to Telegram). Is this the right UX for a research amplification tool? Should there be a web dashboard for deeper analysis?

10. **Integration risk:** Telethon + PTB + AV fetcher + SQLite in one system. What's the most likely integration failure mode?

### For Claude Code S14-CC:

Same questions 1-10 as above, PLUS:

11. **Cross-validate S14 findings:** Where do you disagree with ChatGPT Pro?

12. **Code architecture:** Given the build order (1a→1b→1c), what's the optimal Python package structure? How should modules be organized for a solo developer?

13. **Testing strategy for shadow portfolio:** How do you backtest a discretionary framework? What's the right validation methodology?

14. **Telethon reliability:** Long-running Telethon sessions on VPS — what failure modes? How to handle Telegram session invalidation, rate limits, connection drops?

---

## 12. REFERENCE DOCUMENTS

| Document | Version | Content |
|----------|---------|---------|
| Architecture_Decision_Record_v1.md | 1.0 | Technical ADR (SQLite schema, Policy Engine, build order) |
| Architecture_Discussion_Handoff_2026_03_13.md | 1.0 | Original handoff document |
| Trading_Council_Module_KB_v2.md | 2.0 | Council specs, API contract |
| Temporal_Framework_Future_Modules_v9.md | 9.0 | 16+ modules tracker |
| Project_Roadmap_v10.md | 10.0 | Overall project direction |
| Validation_Sessions_Log_v10.md | 10.0 | 38 validation entries + 13 rejections |
| S13_architecture_cross_validation.md | 1.0 | Claude Code S13-CC full report |

---

*System Vision & Architecture v2.0 | March 14, 2026*
*Market Structure & Trading Systems Project*
*Philosophy: Research Amplification, not Automation*
