"""Tests for xval_budget.py — two-tier XVAL budget manager."""

import time
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import aiosqlite
import pytest
import pytest_asyncio

from market_engine.llm.xval_budget import XvalBudget, _week_start_ts, _today_start_ts

TZ_JERUSALEM = ZoneInfo("Asia/Jerusalem")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS llm_ab_comparison (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_item_id INTEGER,
    gemini_category TEXT,
    sonnet_category TEXT,
    policy_agreement INTEGER,
    xval_type TEXT,
    sampling_bucket TEXT DEFAULT '',
    error_class TEXT,
    sonnet_latency_ms INTEGER DEFAULT 0,
    raw_sonnet_response TEXT DEFAULT '',
    keyword_families TEXT DEFAULT '',
    created_at INTEGER
)
"""


@pytest_asyncio.fixture
async def db():
    """In-memory SQLite database with llm_ab_comparison table."""
    async with aiosqlite.connect(":memory:") as conn:
        await conn.execute(CREATE_TABLE)
        await conn.commit()
        yield conn


async def _insert_call(db, xval_type: str, created_at: int | None = None):
    """Helper: insert a dummy llm_ab_comparison row."""
    ts = created_at or int(time.time())
    await db.execute(
        """
        INSERT INTO llm_ab_comparison
        (news_item_id, gemini_category, sonnet_category, policy_agreement,
         xval_type, created_at)
        VALUES (?, 'other', 'other', 1, ?, ?)
        """,
        (1, xval_type, ts),
    )
    await db.commit()


class TestBudgetTracking:
    """Weekly budget tracking."""

    @pytest.mark.asyncio
    async def test_empty_week_all_allowed(self, db):
        """No calls yet -> all planes allowed."""
        budget = XvalBudget(db)
        ok, reason = await budget.can_call_guard()
        assert ok is True
        assert reason == "ok"
        ok, reason = await budget.can_call_audit_p3()
        assert ok is True
        assert reason == "ok"
        ok, reason = await budget.can_call_nearmiss()
        assert ok is True
        assert reason == "ok"

    @pytest.mark.asyncio
    async def test_guard_always_allowed_under_ceiling(self, db):
        """Guard allowed even when discretionary exhausted."""
        budget = XvalBudget(db)
        # Fill discretionary budget: $1.00 / $0.007 ~= 143 calls
        # Insert 143 audit calls to exhaust discretionary
        now_ts = int(time.time())
        for i in range(143):
            await _insert_call(db, "audit", now_ts)

        ok, reason = await budget.can_call_guard()
        assert ok is True
        assert reason == "ok"

    @pytest.mark.asyncio
    async def test_guard_blocked_at_ceiling(self, db):
        """Guard blocked when total ceiling hit ($1.50)."""
        budget = XvalBudget(db)
        # $1.50 / $0.007 ~= 215 calls total
        now_ts = int(time.time())
        for i in range(215):
            await _insert_call(db, "guard", now_ts)

        ok, reason = await budget.can_call_guard()
        assert ok is False
        assert reason == "weekly_ceiling_exceeded"

    @pytest.mark.asyncio
    async def test_audit_p3_daily_cap(self, db):
        """11th audit call blocked by daily cap (default 10)."""
        budget = XvalBudget(db)
        now_ts = int(time.time())
        for i in range(10):
            await _insert_call(db, "audit", now_ts)

        ok, reason = await budget.can_call_audit_p3()
        assert ok is False
        assert reason == "daily_audit_cap"

    @pytest.mark.asyncio
    async def test_audit_p3_discretionary_exhausted(self, db):
        """Audit blocked when discretionary budget exhausted."""
        budget = XvalBudget(db)
        # Discretionary = $1.00; $1.00 / $0.007 ~= 143 calls
        now_ts = int(time.time())
        for i in range(143):
            await _insert_call(db, "nearmiss", now_ts)

        ok, reason = await budget.can_call_audit_p3()
        assert ok is False
        assert reason == "discretionary_exhausted"

    @pytest.mark.asyncio
    async def test_nearmiss_daily_cap(self, db):
        """6th near-miss call blocked by daily cap (default 5)."""
        budget = XvalBudget(db)
        now_ts = int(time.time())
        for i in range(5):
            await _insert_call(db, "nearmiss", now_ts)

        ok, reason = await budget.can_call_nearmiss()
        assert ok is False
        assert reason == "daily_nearmiss_cap"

    @pytest.mark.asyncio
    async def test_nearmiss_weekly_cap(self, db):
        """26th near-miss call blocked by weekly cap (default 25)."""
        budget = XvalBudget(db)
        # Place all 25 calls within the current week, spread across different
        # days (at most 4-5 per day to avoid hitting daily cap of 5 on "today").
        # Use week_start_ts as base and offset by hours so none land on today.
        week_start = _week_start_ts()
        for i in range(25):
            # Offset each call by i hours from the start of the week
            ts = week_start + (i * 3600) + 60  # +60 to be safely past boundary
            await _insert_call(db, "nearmiss", ts)

        ok, reason = await budget.can_call_nearmiss()
        assert ok is False
        assert reason == "weekly_nearmiss_cap"

    @pytest.mark.asyncio
    async def test_discretionary_exhausted_guard_still_works(self, db):
        """Guard reserved not affected by discretionary exhaustion."""
        budget = XvalBudget(db)
        # Fill discretionary with audit calls
        now_ts = int(time.time())
        for i in range(143):
            await _insert_call(db, "audit", now_ts)

        # Audit should be blocked
        ok_audit, _ = await budget.can_call_audit_p3()
        assert ok_audit is False

        # Guard should still work
        ok_guard, reason = await budget.can_call_guard()
        assert ok_guard is True
        assert reason == "ok"

    @pytest.mark.asyncio
    async def test_weekly_reset(self, db):
        """Calls from previous week don't count."""
        budget = XvalBudget(db)
        # Insert calls from 8 days ago
        old_ts = int((datetime.now(TZ_JERUSALEM) - timedelta(days=8)).timestamp())
        for i in range(200):
            await _insert_call(db, "guard", old_ts)

        # Should be allowed since those are from a previous week
        ok, reason = await budget.can_call_guard()
        assert ok is True
        assert reason == "ok"

    @pytest.mark.asyncio
    async def test_status_output(self, db):
        """get_status() returns correct structure."""
        budget = XvalBudget(db)
        now_ts = int(time.time())
        await _insert_call(db, "guard", now_ts)
        await _insert_call(db, "audit", now_ts)
        await _insert_call(db, "nearmiss", now_ts)

        status = await budget.get_status()
        assert "week_calls" in status
        assert "week_total_calls" in status
        assert "week_cost_usd" in status
        assert "ceiling_usd" in status
        assert "guard_reserved_usd" in status
        assert "discretionary_remaining_usd" in status
        assert status["week_total_calls"] == 3
        assert status["ceiling_usd"] == 1.50
        assert status["guard_reserved_usd"] == 0.50

    @pytest.mark.asyncio
    async def test_cost_calculation(self, db):
        """Cost per call * count = total cost."""
        budget = XvalBudget(db)
        now_ts = int(time.time())
        for i in range(10):
            await _insert_call(db, "guard", now_ts)

        status = await budget.get_status()
        assert status["week_cost_usd"] == round(10 * 0.007, 3)

    @pytest.mark.asyncio
    async def test_week_boundary_jerusalem(self):
        """Week boundary uses Asia/Jerusalem, not UTC."""
        # Just verify the function returns a Monday timestamp in Jerusalem TZ
        ts = _week_start_ts()
        dt = datetime.fromtimestamp(ts, tz=TZ_JERUSALEM)
        assert dt.weekday() == 0  # Monday
        assert dt.hour == 0
        assert dt.minute == 0
        assert dt.second == 0

    @pytest.mark.asyncio
    async def test_today_start_jerusalem(self):
        """Today start uses Asia/Jerusalem."""
        ts = _today_start_ts()
        dt = datetime.fromtimestamp(ts, tz=TZ_JERUSALEM)
        assert dt.hour == 0
        assert dt.minute == 0
        assert dt.second == 0
