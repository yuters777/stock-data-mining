# S14-CC Cross-Validation — Part 3: Implementation Details (CV-7 to CV-10)
# Date: March 20, 2026
# Validator: Claude Code (Opus 4.6)

---

## CV-7: SQLite WAL Consistency During Freeze Step

WAL mode does **not** give you automatic snapshot isolation across multiple independent SELECT statements. Each SELECT establishes its own read snapshot at the moment it begins — if the ingest writer commits between two SELECTs in your freeze step, you read `bars_m5` from time T and `news_items` from time T+δ, producing an inconsistent frozen state. The fix is simple: wrap the entire freeze in a single read transaction.

Use `BEGIN DEFERRED` (the default for `BEGIN`), not `BEGIN IMMEDIATE`. A deferred transaction acquires only a shared read lock on first read — it does not block the ingest writer at all. In WAL mode, readers and writers never block each other anyway (that is WAL's whole point), so the read transaction holds a consistent snapshot while ingest continues writing unimpeded. The concrete pattern:

```python
import aiosqlite

async def freeze_state(db: aiosqlite.Connection) -> FrozenState:
    """Read all inputs for one compute cycle as a consistent snapshot.

    Uses a read transaction so all SELECTs see the same DB state,
    even if the ingest process commits between reads.
    """
    async with db.execute("BEGIN DEFERRED"):
        pass  # aiosqlite needs an execute call to start the txn

    try:
        # All reads within this transaction see the same snapshot
        config = await _read_config_version(db)
        bars = await _read_latest_bars(db, config.watchlist)
        macro = await _read_ib_macro_state(db)
        news = await _read_recent_news_analyses(db, since=cycle_start - timedelta(minutes=10))
        earnings = await _read_upcoming_earnings(db)
        freshness = await _read_freshness_metadata(db)

        return FrozenState(
            cycle_id=cycle_id,
            frozen_at=datetime.utcnow(),
            config=config,
            bars=bars,
            macro=macro,
            news=news,
            earnings=earnings,
            freshness=freshness,
        )
    finally:
        await db.execute("ROLLBACK")  # read-only, nothing to commit
```

Key details: (1) Use a **separate connection** for the freeze/compute/write path vs the ingest writers — SQLite WAL allows one writer and many readers concurrently but only on different connections. (2) The read transaction should be short-lived — freeze the data into in-memory dataclasses, then release the transaction before starting compute. Do not hold the read snapshot open for the entire compute phase; that would prevent WAL checkpointing. (3) For the atomic write in step 6, use `BEGIN IMMEDIATE` — this acquires the write lock upfront and guarantees your multi-table INSERT/UPDATE is atomic. If the ingest writer is mid-transaction, `BEGIN IMMEDIATE` will wait (or raise `SQLITE_BUSY` with a configurable timeout via `PRAGMA busy_timeout`).

```python
async def atomic_write(db: aiosqlite.Connection, cycle: CycleResult):
    """Write all compute results in one transaction (step 6)."""
    await db.execute("PRAGMA busy_timeout = 5000")  # wait up to 5s for write lock
    async with db.execute("BEGIN IMMEDIATE"):
        pass
    try:
        await _write_cycle_metadata(db, cycle)
        await _write_module_states(db, cycle)
        await _write_raw_snapshot(db, cycle)
        await _write_filtered_snapshot(db, cycle)
        await _write_shadow_decisions(db, cycle)
        await _write_event_log_rows(db, cycle)
        await db.execute("COMMIT")
    except Exception:
        await db.execute("ROLLBACK")
        raise
```

---

## CV-8: Anthropic Structured Outputs for Tier 2

S15 is right that prompt-only JSON ("return ONLY a JSON object") is fragile — Claude may add markdown fences, preamble, trailing text, or slightly deviate from the schema. The most reliable approach with the Anthropic API is **tool use (function calling)**, which constrains the model's output to a declared JSON schema. You define the Tier 2 analysis schema as a tool, force the model to call it, and extract the structured result from the tool call arguments. This is more reliable than parsing free-text JSON because the API enforces schema compliance at the generation level.

```python
import anthropic
from typing import Any

client = anthropic.Anthropic()

TIER2_TOOL = {
    "name": "analyze_news",
    "description": "Analyze a financial news message and return structured assessment.",
    "input_schema": {
        "type": "object",
        "properties": {
            "impact_probability": {
                "type": "number",
                "minimum": 0, "maximum": 1,
                "description": "Likelihood of >0.5% price move (0-1)"
            },
            "direction": {
                "type": "string",
                "enum": ["bullish", "bearish", "neutral", "mixed"]
            },
            "primary_tickers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Directly affected tickers"
            },
            "secondary_tickers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Indirectly affected tickers"
            },
            "urgency": {
                "type": "string",
                "enum": ["react_now", "monitor", "background"]
            },
            "category": {
                "type": "string",
                "enum": [
                    "macro_fed", "macro_data", "earnings",
                    "geopolitical", "crypto", "sector", "corporate"
                ]
            },
            "override_relevance": {
                "type": "string",
                "enum": ["high", "medium", "low", "none"]
            },
            "event_penalty_trigger": {"type": "boolean"},
            "geostress_signal": {"type": "boolean"},
            "summary_en": {
                "type": "string",
                "description": "English summary for logs (1-2 sentences)"
            },
            "confidence": {
                "type": "number",
                "minimum": 0, "maximum": 1
            }
        },
        "required": [
            "impact_probability", "direction", "primary_tickers",
            "secondary_tickers", "urgency", "category",
            "override_relevance", "event_penalty_trigger",
            "geostress_signal", "summary_en", "confidence"
        ]
    }
}

async def tier2_analyze(message_text: str, channel: str,
                        market_context: dict) -> dict[str, Any] | None:
    """Call Claude Sonnet via tool use for schema-constrained Tier 2 analysis."""
    system_prompt = (
        "You are a financial news analyst for a trading research system. "
        "Analyze the Telegram channel message using the analyze_news tool. "
        "The trader monitors US equities (NVDA, META, TSLA, GOOGL, AAPL, AMZN, "
        "MSFT, BA, CRWD, PLTR), crypto (BTC, ETH, IBIT, ETHA, COIN, MARA, MSTR), "
        "China ADRs (BABA, BIDU, TCEHY, KWEB), and macro (VIX, oil, gold, DXY, Fed).\n\n"
        f"Current market context:\n"
        f"- VIX: {market_context.get('vix', 'N/A')}\n"
        f"- Override state: {market_context.get('override', 'N/A')}\n"
        f"- Current zone: {market_context.get('zone', 'N/A')}\n"
        f"- Market hours: {market_context.get('market_status', 'N/A')}"
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_prompt,
        tools=[TIER2_TOOL],
        tool_choice={"type": "tool", "name": "analyze_news"},  # force this tool
        messages=[{
            "role": "user",
            "content": f"Telegram message ({channel}):\n{message_text}"
        }]
    )

    # Extract structured result from the forced tool call
    for block in response.content:
        if block.type == "tool_use" and block.name == "analyze_news":
            return block.input  # already a validated dict

    return None  # should not happen with tool_choice forced
```

The `tool_choice: {"type": "tool", "name": "analyze_news"}` forces Claude to call the tool, guaranteeing structured output. The schema's `enum` constraints on `direction`, `urgency`, `category`, etc. prevent invalid values at the API level. This is cheaper than a second validation pass and more robust than regex-parsing JSON from free text. Version the tool schema via `tier2_schema_version` in your config — when you add a field or change an enum, bump the version and store it alongside each `news_analysis` row so you can distinguish results generated under different schemas.

---

## CV-9: systemd Supervision for 3 Processes

Three processes with clear dependencies: IB Gateway (Java) must be up before the main engine can read IB data, and the Telethon ingest process writes to the same SQLite DB as the engine. The Telethon process and the engine have no hard startup ordering — both can start independently and tolerate the other being absent. The engine just sees stale or missing news data and degrades gracefully.

```ini
# /etc/systemd/system/market-ib-gateway.service
[Unit]
Description=IB Gateway (headless via IBC)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=market
WorkingDirectory=/opt/market-system/ibc
ExecStart=/opt/market-system/ibc/scripts/ibcstart.sh
Environment="JAVA_OPTS=-Xmx768m -Xms512m"
Restart=always
RestartSec=30
# IB Gateway does a daily restart ~23:45 ET; systemd auto-restarts it
StartLimitIntervalSec=300
StartLimitBurst=5

# Health: IB Gateway listens on port 4001 (live) or 4002 (paper)
ExecStartPost=/bin/bash -c 'for i in $(seq 1 30); do nc -z 127.0.0.1 4002 && exit 0; sleep 2; done; exit 1'

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/market-ingest.service
[Unit]
Description=Telethon News Ingestion
After=network-online.target
# No dependency on IB Gateway — ingest runs independently

[Service]
Type=simple
User=market
WorkingDirectory=/opt/market-system
ExecStart=/opt/market-system/.venv/bin/python -m market_engine.ingest
EnvironmentFile=/opt/market-system/.env
Restart=always
RestartSec=10
# Telethon session invalidation or flood wait → process exits → systemd restarts
StartLimitIntervalSec=600
StartLimitBurst=10

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/market-engine.service
[Unit]
Description=Market Engine (compute + bot + council)
After=network-online.target market-ib-gateway.service
Wants=market-ib-gateway.service market-ingest.service
# Wants= not Requires= — engine runs degraded if IB is down

[Service]
Type=simple
User=market
WorkingDirectory=/opt/market-system
ExecStart=/opt/market-system/.venv/bin/python -m market_engine.main
EnvironmentFile=/opt/market-system/.env
Restart=always
RestartSec=10
StartLimitIntervalSec=300
StartLimitBurst=5

# Watchdog: engine writes heartbeat to DB every cycle;
# external check via ExecStartPost or a simple timer unit
WatchdogSec=600

[Install]
WantedBy=multi-user.target
```

Key design decisions: (1) `Wants=` not `Requires=` for the engine→IB dependency. `Requires=` would stop the engine if IB Gateway crashes, which is wrong — the engine should continue with Override marked STALE. (2) `After=market-ib-gateway.service` ensures ordering on boot but does not create a hard dependency. (3) The `ExecStartPost` health check on the IB Gateway unit waits up to 60 seconds for port 4002 to be reachable before declaring the unit started. (4) `RestartSec=30` for IB Gateway (Java startup is slow) vs `RestartSec=10` for the Python processes. (5) All three run as a dedicated `market` user, not root. (6) `WatchdogSec=600` on the engine means systemd kills and restarts it if the process doesn't call `sd_notify(WATCHDOG=1)` within 10 minutes — integrate via `systemd.daemon.notify("WATCHDOG=1")` in your heartbeat write at step 7 of the compute cycle.

---

## CV-10: Python Package Structure

The layout must accommodate three constraints: (1) Phase 1a → 1b → 1c incremental builds without refactoring, (2) eventual 16+ modules, and (3) clear boundaries between data ingestion, computation, analysis, and output. A flat-ish domain-based layout is best — avoid deep nesting, avoid premature abstraction into `core/`/`shared/`/`common/` catch-all packages.

```
market-engine/
├── pyproject.toml
├── .env.example
├── tests/
│   ├── conftest.py              # shared fixtures: in-memory DB, sample bars, etc.
│   ├── test_fetcher.py          # Phase 1a
│   ├── test_news_tier1.py       # Phase 1a
│   ├── test_news_tier2.py       # Phase 1b
│   ├── test_ema.py              # Phase 1b
│   ├── test_override.py         # Phase 1b
│   ├── test_zone.py             # Phase 1b
│   ├── test_policy_engine.py    # Phase 1b
│   ├── test_compute_cycle.py    # Phase 1b
│   ├── test_shadow.py           # Phase 1c
│   ├── test_pattern.py          # Phase 1c
│   └── replay/
│       ├── day4_expected.json   # golden-day replay fixtures
│       └── day5_expected.json
├── deploy/
│   ├── market-engine.service
│   ├── market-ingest.service
│   └── market-ib-gateway.service
└── src/
    └── market_engine/
        ├── __init__.py
        ├── main.py              # asyncio entrypoint, scheduler, bot setup
        ├── ingest.py            # Telethon entrypoint (separate process)
        │
        ├── db/
        │   ├── __init__.py
        │   ├── schema.py        # CREATE TABLE statements, migrations
        │   ├── connection.py    # connection factory, WAL setup, busy_timeout
        │   └── queries.py       # typed read/write functions (not raw SQL scattered)
        │
        ├── data/                # Phase 1a — ingestion modules
        │   ├── __init__.py
        │   ├── av_fetcher.py    # Alpha Vantage M5 bars daemon
        │   ├── av_news.py       # AV News Sentiment API
        │   ├── av_earnings.py   # AV Earnings Calendar
        │   ├── news_tier1.py    # Telegram message parsing, ticker extraction, aliases
        │   ├── news_tier2.py    # Claude API structured analysis (Phase 1b)
        │   └── ib_bridge.py     # IB Gateway wrapper (Phase 1b)
        │
        ├── compute/             # Phase 1b — framework state computation
        │   ├── __init__.py
        │   ├── cycle.py         # 7-step compute cycle orchestrator
        │   ├── freeze.py        # step 3: consistent snapshot reader
        │   ├── ema.py           # EMA 9/21 Gate, 4H synthesis, TrendStateScore
        │   ├── override.py      # Override 3.0 state machine (7 components)
        │   ├── zone.py          # 5-Zone Temporal Grid, DST handling
        │   └── policy_engine.py # precedence hierarchy + 13 rejections
        │
        ├── analysis/            # Phase 1c — pattern detection & shadow
        │   ├── __init__.py
        │   ├── shadow.py        # Shadow portfolio, score-bucket entry/exit
        │   ├── veto.py          # Veto analysis (correct/missed/inconclusive)
        │   ├── pattern.py       # Pattern detector (anomalies, divergences)
        │   ├── hypothesis.py    # N-count tracker, independent episodes
        │   └── auto_research.py # Council-based mini-DR
        │
        ├── output/              # Reporting & user interaction
        │   ├── __init__.py
        │   ├── bot.py           # PTB Telegram bot handlers
        │   ├── scorecard.py     # 4-tier daily scorecard generation
        │   ├── alerts.py        # Telegram alert formatting & sending
        │   └── report.py        # Daily report builder
        │
        ├── config/              # Configuration & versioning
        │   ├── __init__.py
        │   ├── settings.py      # Pydantic settings from .env + config_versions table
        │   ├── watchlist.py     # Ticker watchlist, aliases, groups
        │   └── versions.py      # deploy_version + research_config_version tracking
        │
        └── models/              # Shared dataclasses / typed structures
            ├── __init__.py
            ├── market.py        # Bar, Ticker, MacroState
            ├── news.py          # NewsItem, Tier1Result, Tier2Result
            ├── framework.py     # EMAState, OverrideState, ZoneState, Snapshot
            ├── shadow.py        # ShadowPosition, ShadowDecision
            └── cycle.py         # FrozenState, CycleResult, CycleMetadata
```

Design rationale: (1) **`models/` contains only dataclasses** — no business logic, no DB access. These are the typed structures that flow between layers. Every module imports from models, nothing else imports from models, so there are no circular dependencies. (2) **`db/` centralizes all SQL** — modules call `db.queries.read_latest_bars(conn, tickers)` rather than embedding raw SQL. This makes schema changes a single-point edit. (3) **Each top-level package maps to a phase**: `data/` = Phase 1a, `compute/` = Phase 1b, `analysis/` = Phase 1c, `output/` = all phases. When Phase 1a ships, `compute/` and `analysis/` are empty stubs or don't exist yet — no dead code. (4) **Two entrypoints**: `main.py` (engine + bot + scheduler) and `ingest.py` (Telethon), matching the two Python systemd units. (5) **Tests mirror the structure** with one test file per module, plus `replay/` for golden-day fixtures. (6) The layout accommodates 16+ modules without refactoring — future additions like `data/deribit.py`, `data/stocktwits.py`, `compute/geostress.py`, `analysis/twap.py`, `output/dashboard.py` each go in the obvious location.
