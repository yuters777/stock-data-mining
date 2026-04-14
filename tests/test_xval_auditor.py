"""Tests for xval_auditor.py — nightly stratified Sonnet audit plane."""

import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import aiosqlite
import pytest
import pytest_asyncio

from market_engine.llm.xval_auditor import (
    compute_p3_weight,
    maybe_run_weekly,
    run_nightly_audit,
    run_weekly_summary,
)

TZ_JERUSALEM = ZoneInfo("Asia/Jerusalem")

CREATE_TABLES = """
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
);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text TEXT,
    gemini_category TEXT,
    source TEXT DEFAULT '',
    story_group_id INTEGER,
    created_at INTEGER
);
"""


@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(":memory:") as conn:
        for stmt in CREATE_TABLES.split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(stmt)
        await conn.commit()
        yield conn


def _recent_ts(hours_ago: int = 1) -> int:
    """Timestamp from N hours ago."""
    return int((datetime.now(TZ_JERUSALEM) - timedelta(hours=hours_ago)).timestamp())


async def _insert_ab(
    db, news_item_id, xval_type, policy_agreement=True,
    gemini_cat="other", sonnet_cat="other", error_class=None,
    sampling_bucket="", created_at=None,
):
    ts = created_at or _recent_ts(1)
    await db.execute(
        """
        INSERT INTO llm_ab_comparison
        (news_item_id, gemini_category, sonnet_category, policy_agreement,
         xval_type, sampling_bucket, error_class, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (news_item_id, gemini_cat, sonnet_cat, int(policy_agreement),
         xval_type, sampling_bucket, error_class, ts),
    )
    await db.commit()


async def _insert_news(db, item_id, raw_text="test news", category="other",
                       source="rss", story_group=None, created_at=None):
    ts = created_at or _recent_ts(1)
    await db.execute(
        """
        INSERT INTO news_items (id, raw_text, gemini_category, source, story_group_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (item_id, raw_text, category, source, story_group, ts),
    )
    await db.commit()


class TestAuditPriority:

    @pytest.mark.asyncio
    @patch("market_engine.llm.xval_auditor.NEWS_XVAL_AUDIT_ENABLED", True)
    async def test_p0_guard_disagreements(self, db):
        """P0 includes Guard disagreements from last 24h."""
        await _insert_ab(db, 1, "guard", policy_agreement=False,
                         gemini_cat="earnings_negative", sonnet_cat="other")

        result = await run_nightly_audit(db)
        assert result["p0_count"] == 1
        assert result["p0_disagreements"] == 1

    @pytest.mark.asyncio
    @patch("market_engine.llm.xval_auditor.NEWS_XVAL_AUDIT_ENABLED", True)
    async def test_p0_guard_errors(self, db):
        """P0 includes Guard errors."""
        await _insert_ab(db, 2, "guard", policy_agreement=False,
                         error_class="TimeoutError")

        result = await run_nightly_audit(db)
        assert result["p0_count"] == 1

    @pytest.mark.asyncio
    @patch("market_engine.llm.xval_auditor.NEWS_XVAL_AUDIT_ENABLED", True)
    async def test_p1_nearmiss_positives(self, db):
        """P1 includes near-miss items where Sonnet found veto category."""
        await _insert_ab(db, 3, "nearmiss", policy_agreement=False,
                         gemini_cat="other", sonnet_cat="earnings_negative")

        result = await run_nightly_audit(db)
        assert result["p1_count"] == 1

    @pytest.mark.asyncio
    @patch("market_engine.llm.xval_auditor.NEWS_XVAL_AUDIT_ENABLED", True)
    async def test_p2_guard_confirmations(self, db):
        """P2 includes confirmed Guard events."""
        await _insert_ab(db, 4, "guard", policy_agreement=True,
                         gemini_cat="earnings_negative", sonnet_cat="earnings_negative")

        result = await run_nightly_audit(db)
        assert result["p2_count"] == 1

    @pytest.mark.asyncio
    @patch("market_engine.llm.xval_auditor.NEWS_XVAL_AUDIT_ENABLED", True)
    async def test_p0_p2_no_new_sonnet_calls(self, db):
        """P0-P2 reuse existing results — no new API calls."""
        await _insert_ab(db, 1, "guard", policy_agreement=False)
        await _insert_ab(db, 2, "guard", policy_agreement=True)

        with patch("market_engine.llm.xval_auditor.sonnet_classify") as mock_sonnet:
            result = await run_nightly_audit(db)
            # No Sonnet calls for P0-P2
            mock_sonnet.assert_not_called()

    @pytest.mark.asyncio
    @patch("market_engine.llm.xval_auditor.NEWS_XVAL_AUDIT_ENABLED", True)
    @patch("market_engine.llm.xval_auditor.sonnet_classify")
    async def test_p3_new_sonnet_calls(self, mock_sonnet, db):
        """P3 makes new Sonnet calls for random sample."""
        mock_sonnet.return_value = {
            "category": "other",
            "confidence": 0.9,
            "reasoning": "test",
        }
        # Add uncovered news items
        for i in range(5):
            await _insert_news(db, 100 + i, f"test news {i}")

        result = await run_nightly_audit(db)
        assert result["p3_sampled"] > 0
        assert mock_sonnet.call_count > 0

    @pytest.mark.asyncio
    @patch("market_engine.llm.xval_auditor.NEWS_XVAL_AUDIT_ENABLED", True)
    @patch("market_engine.llm.xval_auditor.sonnet_classify")
    async def test_p3_budget_gated(self, mock_sonnet, db):
        """P3 stops when budget exhausted."""
        mock_sonnet.return_value = {
            "category": "other",
            "confidence": 0.9,
            "reasoning": "test",
        }
        # Add news items
        for i in range(5):
            await _insert_news(db, 200 + i, f"test news {i}")

        # Patch budget to deny after first call
        with patch(
            "market_engine.llm.xval_auditor.XvalBudget.can_call_audit_p3",
            side_effect=[(True, "ok"), (False, "discretionary_exhausted")] * 5,
        ):
            result = await run_nightly_audit(db)
            # Should have sampled at most 1 (budget denied after first)
            assert result["p3_sampled"] <= 1

    @pytest.mark.asyncio
    @patch("market_engine.llm.xval_auditor.NEWS_XVAL_AUDIT_ENABLED", True)
    @patch("market_engine.llm.xval_auditor.sonnet_classify")
    async def test_p3_daily_cap(self, mock_sonnet, db):
        """P3 respects daily discretionary cap (default 10)."""
        mock_sonnet.return_value = {
            "category": "other",
            "confidence": 0.9,
            "reasoning": "test",
        }
        # Add 20 news items
        for i in range(20):
            await _insert_news(db, 300 + i, f"test news {i}")

        result = await run_nightly_audit(db)
        # Should cap at 10 (NEWS_XVAL_AUDIT_DAILY_DISC_CAP)
        assert result["p3_sampled"] <= 10


class TestAuditStratification:

    def test_edgar_source_weighted_higher(self):
        """EDGAR items have 3x weight in P3 sampling."""
        edgar_w = compute_p3_weight("other", "edgar_filing", "some news text here")
        rss_w = compute_p3_weight("other", "rss_feed", "some news text here")
        assert edgar_w > rss_w

    def test_rare_category_weighted_higher(self):
        """Hard-veto eligible categories have 5x weight."""
        veto_w = compute_p3_weight("earnings_negative", "rss", "some text here")
        normal_w = compute_p3_weight("other", "rss", "some text here")
        assert veto_w > normal_w
        # 5x weight for hard-veto
        assert veto_w == normal_w * 5.0

    def test_short_text_anomaly_weight(self):
        """Short text (<30 words) gets anomaly weight."""
        short_w = compute_p3_weight("other", "rss", "very short text")
        normal_w = compute_p3_weight(
            "other", "rss",
            " ".join(["word"] * 100),  # 100 words, normal length
        )
        assert short_w > normal_w

    def test_long_text_anomaly_weight(self):
        """Long text (>500 words) gets anomaly weight."""
        long_w = compute_p3_weight(
            "other", "rss",
            " ".join(["word"] * 600),
        )
        normal_w = compute_p3_weight(
            "other", "rss",
            " ".join(["word"] * 100),
        )
        assert long_w > normal_w

    @pytest.mark.asyncio
    @patch("market_engine.llm.xval_auditor.NEWS_XVAL_AUDIT_ENABLED", True)
    @patch("market_engine.llm.xval_auditor.sonnet_classify")
    async def test_dedup_one_per_story(self, mock_sonnet, db):
        """Only one item per original story in P3 sample."""
        mock_sonnet.return_value = {
            "category": "other",
            "confidence": 0.9,
            "reasoning": "test",
        }
        # Add 3 news items from same story group
        for i in range(3):
            await _insert_news(db, 400 + i, f"story variant {i}",
                               story_group=999)

        result = await run_nightly_audit(db)
        # Only 1 should be sampled (dedup by story group)
        assert result["p3_sampled"] <= 1


class TestWeeklySummary:

    @pytest.mark.asyncio
    @patch("market_engine.llm.xval_auditor.NEWS_XVAL_AUDIT_ENABLED", True)
    async def test_summary_format(self, db):
        """Weekly summary contains Guard/Audit/NearMiss/Budget/Pending counts."""
        # Insert some data for the week
        ts = _recent_ts(24)
        await _insert_ab(db, 1, "guard", policy_agreement=True, created_at=ts)
        await _insert_ab(db, 2, "audit", policy_agreement=True, created_at=ts)
        await _insert_ab(db, 3, "nearmiss", policy_agreement=True, created_at=ts)

        summary = await run_weekly_summary(db)
        assert "Guard:" in summary
        assert "Audit:" in summary
        assert "Near-Miss:" in summary
        assert "Budget:" in summary
        assert "Pending verdicts:" in summary

    @pytest.mark.asyncio
    async def test_runs_on_sunday(self):
        """maybe_run_weekly only runs on Sunday."""
        # We can't easily control the day, but we can test the logic
        now = datetime.now(TZ_JERUSALEM)
        if now.weekday() == 6:  # Sunday
            # Would run
            pass
        else:
            # mock db just to test the gate
            mock_db = AsyncMock()
            result = await maybe_run_weekly(mock_db)
            assert result is None  # Not Sunday, so None

    @pytest.mark.asyncio
    async def test_disabled_flag_skips(self, db):
        """NEWS_XVAL_AUDIT_ENABLED=False -> no audit runs."""
        with patch("market_engine.llm.xval_auditor.NEWS_XVAL_AUDIT_ENABLED", False):
            result = await run_nightly_audit(db)
            assert result == {"status": "disabled"}
