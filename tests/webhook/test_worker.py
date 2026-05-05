"""Tests for webhook/worker.py — Wave 5b migration verification."""
import asyncio
import tempfile
from pathlib import Path

import pytest

from market_engine.db.migrations import run_migrations
from market_engine.webhook.worker import (
    TradeEvent,
    enqueue_telegram,
    fetch_symbol_context,
    ingest_event,
    mark_dispatch_sent,
    process_trade_event,
    record_processing_decision,
    validate_event,
    TelegramDispatch,
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    asyncio.get_event_loop().run_until_complete(run_migrations(path))
    return path


def test_ingest_event(db_path: str) -> None:
    event = TradeEvent(symbol="AAPL", event_type="BUY", payload={"price": 180.0})
    event_id = asyncio.get_event_loop().run_until_complete(ingest_event(db_path, event))
    assert isinstance(event_id, int)
    assert event_id >= 1


def test_validate_event_ok(db_path: str) -> None:
    event = TradeEvent(symbol="AAPL", event_type="BUY", payload={})
    event_id = asyncio.get_event_loop().run_until_complete(ingest_event(db_path, event))
    result = asyncio.get_event_loop().run_until_complete(validate_event(db_path, event_id, event))
    assert result.status == "ok"
    assert result.reason is None


def test_validate_event_rejected_bad_symbol(db_path: str) -> None:
    event = TradeEvent(symbol="", event_type="BUY", payload={})
    event_id = asyncio.get_event_loop().run_until_complete(ingest_event(db_path, event))
    result = asyncio.get_event_loop().run_until_complete(validate_event(db_path, event_id, event))
    assert result.status == "rejected"
    assert result.reason == "invalid_symbol"


def test_validate_event_rejected_unknown_type(db_path: str) -> None:
    event = TradeEvent(symbol="MSFT", event_type="HOLD", payload={})
    event_id = asyncio.get_event_loop().run_until_complete(ingest_event(db_path, event))
    result = asyncio.get_event_loop().run_until_complete(validate_event(db_path, event_id, event))
    assert result.status == "rejected"
    assert result.reason == "unknown_event_type"


def test_fetch_symbol_context_empty(db_path: str) -> None:
    ctx = asyncio.get_event_loop().run_until_complete(fetch_symbol_context(db_path, "GOOG"))
    assert ctx == {}


def test_record_processing_decision(db_path: str) -> None:
    event = TradeEvent(symbol="TSLA", event_type="SELL", payload={})
    event_id = asyncio.get_event_loop().run_until_complete(ingest_event(db_path, event))
    asyncio.get_event_loop().run_until_complete(
        record_processing_decision(db_path, event_id, "processed", {"note": "ok"})
    )


def test_enqueue_and_mark_dispatch(db_path: str) -> None:
    event = TradeEvent(symbol="NVDA", event_type="BUY", payload={})
    event_id = asyncio.get_event_loop().run_until_complete(ingest_event(db_path, event))
    dispatch = TelegramDispatch(chat_id="-100123", message="[BUY] NVDA", event_id=event_id)
    dispatch_id = asyncio.get_event_loop().run_until_complete(enqueue_telegram(db_path, dispatch))
    assert dispatch_id >= 1
    asyncio.get_event_loop().run_until_complete(mark_dispatch_sent(db_path, dispatch_id))


def test_process_trade_event_full_lifecycle(db_path: str) -> None:
    raw = {"symbol": "AMD", "event_type": "BUY", "chat_id": "-100456", "price": 120.0}
    result = asyncio.get_event_loop().run_until_complete(process_trade_event(db_path, raw))
    assert result["status"] == "processed"
    assert "event_id" in result
    assert "dispatch_id" in result


def test_process_trade_event_rejected(db_path: str) -> None:
    raw = {"symbol": "", "event_type": "BUY"}
    result = asyncio.get_event_loop().run_until_complete(process_trade_event(db_path, raw))
    assert result["status"] == "rejected"
    assert result["reason"] == "invalid_symbol"


def test_no_raw_aiosqlite_connect_in_worker() -> None:
    """Wave 5b: worker.py must not contain aiosqlite.connect()."""
    src = Path(__file__).resolve().parents[2] / "src/market_engine/webhook/worker.py"
    assert src.exists()
    assert "aiosqlite.connect" not in src.read_text(), \
        "worker.py still has raw aiosqlite.connect() — Wave 5b migration incomplete"


def test_no_raw_aiosqlite_connect_in_app() -> None:
    """Wave 5b: app.py must not contain aiosqlite.connect()."""
    src = Path(__file__).resolve().parents[2] / "src/market_engine/webhook/app.py"
    assert src.exists()
    assert "aiosqlite.connect" not in src.read_text(), \
        "app.py still has raw aiosqlite.connect() — Wave 5b migration incomplete"
