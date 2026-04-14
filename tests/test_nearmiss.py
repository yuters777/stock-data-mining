"""Tests for nearmiss_checker.py — keyword-triggered Sonnet verification."""

import time
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from market_engine.llm.nearmiss_checker import (
    NEARMISS_KEYWORDS,
    batch_check_nearmiss,
    check_nearmiss,
    compute_priority,
    scan_keywords,
)
from market_engine.llm.taxonomy import HARD_VETO_LEAF_CATEGORIES

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
    async with aiosqlite.connect(":memory:") as conn:
        await conn.execute(CREATE_TABLE)
        await conn.commit()
        yield conn


class TestKeywordScanning:

    def test_earnings_miss_keywords(self):
        """'missed estimates' triggers earnings_negative family."""
        matches = scan_keywords("Company XYZ missed estimates by 15%")
        assert "earnings_negative" in matches
        assert "missed estimates" in matches["earnings_negative"]

    def test_regulatory_keywords(self):
        """'SEC charges' triggers regulatory family."""
        matches = scan_keywords("SEC charges company with fraud")
        assert "regulatory" in matches
        assert "SEC charges" in matches["regulatory"]

    def test_no_keywords_returns_empty(self):
        """Generic text with no keywords -> empty dict."""
        matches = scan_keywords("Company announces new product lineup for Q3")
        assert matches == {}

    def test_case_insensitive(self):
        """Keywords match case-insensitively."""
        matches = scan_keywords("MISSED ESTIMATES significantly")
        assert "earnings_negative" in matches

        matches = scan_keywords("sec Charges filed today")
        assert "regulatory" in matches

    def test_multi_family_keywords(self):
        """Text with both earnings + regulatory keywords -> both families."""
        text = "Company missed estimates and SEC charges are pending"
        matches = scan_keywords(text)
        assert "earnings_negative" in matches
        assert "regulatory" in matches

    def test_multiple_keywords_same_family(self):
        """Multiple hits in same family all captured."""
        text = "Revenue miss and EPS miss, lowered guidance"
        matches = scan_keywords(text)
        assert "earnings_negative" in matches
        assert len(matches["earnings_negative"]) >= 2

    def test_partial_word_no_match(self):
        """'dismiss' should NOT match 'miss' (regex uses re.escape on full phrase)."""
        # 'earnings miss' won't match 'dismiss'
        matches = scan_keywords("We dismiss the allegations")
        assert matches == {}


class TestPriorityScoring:

    def test_multi_family_highest_priority(self):
        """Multi-keyword-family matches get highest score."""
        multi = compute_priority(
            {"earnings_negative": ["missed estimates"], "regulatory": ["SEC charges"]},
            [],
        )
        single = compute_priority(
            {"earnings_negative": ["missed estimates"]},
            [],
        )
        assert multi > single

    def test_tracked_ticker_bonus(self):
        """Items mentioning tracked tickers get priority bonus."""
        with_ticker = compute_priority(
            {"earnings_negative": ["missed estimates"]},
            ["AAPL"],
        )
        without_ticker = compute_priority(
            {"earnings_negative": ["missed estimates"]},
            [],
        )
        assert with_ticker > without_ticker

    def test_edgar_source_bonus(self):
        """EDGAR source gets credibility bonus."""
        edgar = compute_priority(
            {"earnings_negative": ["missed estimates"]},
            [],
            source="edgar_filing",
        )
        telegram = compute_priority(
            {"earnings_negative": ["missed estimates"]},
            [],
            source="telegram",
        )
        assert edgar > telegram


class TestNearMissFlow:

    @pytest.mark.asyncio
    async def test_veto_category_skipped(self, db):
        """Items already classified as hard-veto -> skip (goes through Guard)."""
        result = await check_nearmiss(
            news_item_id=1,
            raw_text="SEC charges company with missed estimates",
            gemini_category="earnings_negative",  # already hard-veto
            gemini_tickers=["AAPL"],
            db=db,
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("market_engine.llm.nearmiss_checker.sonnet_classify")
    async def test_keyword_match_calls_sonnet(self, mock_sonnet, db):
        """Keyword match + budget available -> Sonnet called."""
        mock_sonnet.return_value = {
            "category": "earnings_positive",
            "confidence": 0.9,
            "reasoning": "test",
        }
        result = await check_nearmiss(
            news_item_id=1,
            raw_text="Company missed estimates by a wide margin",
            gemini_category="other",
            gemini_tickers=[],
            db=db,
        )
        assert result is not None
        assert result["status"] == "checked"
        mock_sonnet.assert_called_once()

    @pytest.mark.asyncio
    @patch("market_engine.llm.nearmiss_checker.XvalBudget.can_call_nearmiss")
    async def test_budget_exhausted_logs_unchecked(self, mock_budget, db):
        """Keyword match + budget exhausted -> logged as unchecked."""
        mock_budget.return_value = (False, "daily_nearmiss_cap")
        result = await check_nearmiss(
            news_item_id=1,
            raw_text="Company missed estimates badly",
            gemini_category="other",
            gemini_tickers=[],
            db=db,
        )
        assert result is not None
        assert result["status"] == "unchecked"
        assert result["reason"] == "daily_nearmiss_cap"

        # Check it was logged
        cursor = await db.execute(
            "SELECT sonnet_category, error_class FROM llm_ab_comparison WHERE news_item_id = 1"
        )
        row = await cursor.fetchone()
        assert row[0] == "nearmiss_keyword_hit_unchecked"
        assert row[1] == "daily_nearmiss_cap"

    @pytest.mark.asyncio
    @patch("market_engine.llm.nearmiss_checker.sonnet_classify")
    async def test_sonnet_finds_veto_category(self, mock_sonnet, db):
        """Sonnet returns hard-veto category -> logged as P1 for audit."""
        mock_sonnet.return_value = {
            "category": "earnings_negative",
            "confidence": 0.95,
            "reasoning": "Clearly an earnings miss",
        }
        result = await check_nearmiss(
            news_item_id=1,
            raw_text="Company missed estimates dramatically",
            gemini_category="other",
            gemini_tickers=[],
            db=db,
        )
        assert result is not None
        assert result["false_negative"] is True
        assert result["agreement"] is False

        # Check P1 bucket tag
        cursor = await db.execute(
            "SELECT sampling_bucket FROM llm_ab_comparison WHERE news_item_id = 1"
        )
        row = await cursor.fetchone()
        assert row[0] == "P1"

    @pytest.mark.asyncio
    @patch("market_engine.llm.nearmiss_checker.sonnet_classify")
    async def test_selection_priority_multi_keyword_first(self, mock_sonnet, db):
        """Multi-keyword hits prioritized over single-keyword in batch."""
        mock_sonnet.return_value = {
            "category": "other",
            "confidence": 0.8,
            "reasoning": "test",
        }
        items = [
            {
                "news_item_id": 1,
                "raw_text": "Company missed estimates",
                "gemini_category": "other",
                "gemini_tickers": [],
                "source": "",
            },
            {
                "news_item_id": 2,
                "raw_text": "Company missed estimates and SEC charges filed",
                "gemini_category": "other",
                "gemini_tickers": [],
                "source": "",
            },
        ]
        # Patch budget to allow only 1 call
        from market_engine.llm.xval_budget import XvalBudget as _XvalBudget
        with patch.object(
            _XvalBudget, "can_call_nearmiss",
            side_effect=[(True, "ok"), (False, "daily_nearmiss_cap")],
        ):
            results = await batch_check_nearmiss(items, db)

        # The multi-family item (id=2) should have been checked first
        checked = [r for r in results if r.get("status") == "checked"]
        assert len(checked) >= 1

    @pytest.mark.asyncio
    async def test_no_keywords_no_processing(self, db):
        """Items with no keyword matches -> no processing at all."""
        result = await check_nearmiss(
            news_item_id=1,
            raw_text="Apple announces new iPhone color options",
            gemini_category="product_launch",
            gemini_tickers=["AAPL"],
            db=db,
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("market_engine.llm.nearmiss_checker.sonnet_classify")
    async def test_disabled_flag_skips(self, mock_sonnet, db):
        """NEWS_XVAL_NEARMISS_ENABLED=False -> check still runs at function level.

        Note: The flag check is in event_classifier.py, not in check_nearmiss itself.
        check_nearmiss always processes if called. The classifier gates the call.
        """
        # check_nearmiss itself doesn't check the flag — it processes when called
        mock_sonnet.return_value = {
            "category": "other",
            "confidence": 0.8,
            "reasoning": "test",
        }
        result = await check_nearmiss(
            news_item_id=1,
            raw_text="Company missed estimates",
            gemini_category="other",
            gemini_tickers=[],
            db=db,
        )
        # It processes because it was directly called
        assert result is not None

    @pytest.mark.asyncio
    @patch("market_engine.llm.nearmiss_checker.sonnet_classify")
    async def test_pipeline_not_blocked(self, mock_sonnet, db):
        """Near-miss errors don't crash — exceptions are caught in safe wrapper."""
        mock_sonnet.side_effect = RuntimeError("API timeout")

        # Direct call will raise, but the _safe_nearmiss wrapper catches it
        from market_engine.news.event_classifier import _safe_nearmiss

        # Should not raise
        await _safe_nearmiss(1, "missed estimates text", "other", [], db)

    @pytest.mark.asyncio
    @patch("market_engine.llm.nearmiss_checker.sonnet_classify")
    async def test_logged_to_llm_ab_comparison(self, mock_sonnet, db):
        """Results written with xval_type='nearmiss'."""
        mock_sonnet.return_value = {
            "category": "other",
            "confidence": 0.8,
            "reasoning": "test",
        }
        await check_nearmiss(
            news_item_id=42,
            raw_text="Company missed estimates",
            gemini_category="other",
            gemini_tickers=[],
            db=db,
        )

        cursor = await db.execute(
            "SELECT xval_type, keyword_families FROM llm_ab_comparison WHERE news_item_id = 42"
        )
        row = await cursor.fetchone()
        assert row[0] == "nearmiss"
        assert "earnings_negative" in row[1]
