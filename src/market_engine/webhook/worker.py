"""
Webhook trade-event worker.

Processes inbound trade events through a request lifecycle:
  ingest → validate → enrich → process → telegram dispatch → ack

All DB access uses open_db() from market_engine.db.connection so that the
7 production PRAGMAs (WAL, busy_timeout, synchronous, …) are applied
consistently.  Wave 5b: migrated 6 raw connect call-sites to open_db().
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_engine.db.connection import open_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeEvent:
    symbol: str
    event_type: str
    payload: dict[str, Any]
    received_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

@dataclass
class ValidationResult:
    event_id: int
    status: str
    reason: str | None = None

@dataclass
class TelegramDispatch:
    chat_id: str
    message: str
    event_id: int

# ---------------------------------------------------------------------------
# Stage 1 – event ingest  (~line 61)
# ---------------------------------------------------------------------------

async def ingest_event(db_path: str | Path, event: TradeEvent) -> int:
    """Persist raw event to DB and return its row-id."""
    async with open_db(db_path) as db:
        cur = await db.execute(
            "INSERT INTO trade_events (symbol, event_type, payload, received_at)"
            " VALUES (?, ?, ?, ?)",
            (event.symbol, event.event_type, json.dumps(event.payload), event.received_at),
        )
        await db.commit()
        event_id = cur.lastrowid
    logger.debug("ingested event_id=%d symbol=%s", event_id, event.symbol)
    return event_id

# ---------------------------------------------------------------------------
# Stage 2 – validation  (~line 87)
# ---------------------------------------------------------------------------

async def validate_event(db_path: str | Path, event_id: int, event: TradeEvent) -> ValidationResult:
    """Apply validation rules and persist result."""
    status = "ok"
    reason = None
    if not event.symbol or len(event.symbol) > 10:
        status = "rejected"
        reason = "invalid_symbol"
    elif event.event_type not in {"BUY", "SELL", "CANCEL"}:
        status = "rejected"
        reason = "unknown_event_type"

    async with open_db(db_path) as db:
        await db.execute(
            "INSERT INTO trade_validations (event_id, status, reason) VALUES (?, ?, ?)",
            (event_id, status, reason),
        )
        await db.commit()
    return ValidationResult(event_id=event_id, status=status, reason=reason)

# ---------------------------------------------------------------------------
# Stage 3 – enrichment lookup  (~line 101)
# ---------------------------------------------------------------------------

async def fetch_symbol_context(db_path: str | Path, symbol: str) -> dict[str, Any]:
    """Read cached FMP data for enrichment; return empty dict if no data."""
    async with open_db(db_path) as db:
        row = await (await db.execute(
            "SELECT eps_actual, eps_est, rev_actual, rev_est FROM fmp_earnings"
            " WHERE symbol=? ORDER BY date DESC LIMIT 1",
            (symbol,),
        )).fetchone()
    if row is None:
        return {}
    return dict(row)

# ---------------------------------------------------------------------------
# Stage 4 – processing decision  (~line 108)
# ---------------------------------------------------------------------------

async def record_processing_decision(
    db_path: str | Path, event_id: int, decision: str, meta: dict[str, Any]
) -> None:
    """Upsert the processing outcome for an event."""
    async with open_db(db_path) as db:
        await db.execute(
            "INSERT OR REPLACE INTO trade_validations (event_id, status, reason)"
            " VALUES (?, ?, ?)",
            (event_id, decision, json.dumps(meta)),
        )
        await db.commit()

# ---------------------------------------------------------------------------
# Stage 5 – telegram dispatch prep  (~line 131)
# ---------------------------------------------------------------------------

async def enqueue_telegram(db_path: str | Path, dispatch: TelegramDispatch) -> int:
    """Persist a telegram dispatch record and return its id."""
    async with open_db(db_path) as db:
        cur = await db.execute(
            "INSERT INTO telegram_dispatches (event_id, chat_id, message)"
            " VALUES (?, ?, ?)",
            (dispatch.event_id, dispatch.chat_id, dispatch.message),
        )
        await db.commit()
        row_id = cur.lastrowid
    return row_id

# ---------------------------------------------------------------------------
# Stage 6 – post-dispatch status update  (~line 172)
# ---------------------------------------------------------------------------

async def mark_dispatch_sent(db_path: str | Path, dispatch_id: int) -> None:
    """Update sent_at timestamp after successful telegram delivery."""
    ts = datetime.now(timezone.utc).isoformat()
    async with open_db(db_path) as db:
        await db.execute(
            "UPDATE telegram_dispatches SET sent_at=? WHERE id=?",
            (ts, dispatch_id),
        )
        await db.commit()
    logger.debug("dispatch_id=%d marked sent at %s", dispatch_id, ts)

# ---------------------------------------------------------------------------
# Full lifecycle orchestration
# ---------------------------------------------------------------------------

async def process_trade_event(db_path: str | Path, raw: dict[str, Any]) -> dict[str, Any]:
    """End-to-end event handler called from webhook route."""
    event = TradeEvent(
        symbol=raw.get("symbol", ""),
        event_type=raw.get("event_type", ""),
        payload=raw,
    )

    event_id = await ingest_event(db_path, event)
    validation = await validate_event(db_path, event_id, event)

    if validation.status != "ok":
        return {"event_id": event_id, "status": "rejected", "reason": validation.reason}

    context = await fetch_symbol_context(db_path, event.symbol)
    await record_processing_decision(db_path, event_id, "processed", context)

    message = f"[{event.event_type}] {event.symbol} @ {event.received_at}"
    dispatch = TelegramDispatch(
        chat_id=raw.get("chat_id", ""),
        message=message,
        event_id=event_id,
    )
    dispatch_id = await enqueue_telegram(db_path, dispatch)
    await mark_dispatch_sent(db_path, dispatch_id)

    return {"event_id": event_id, "status": "processed", "dispatch_id": dispatch_id}
