"""
News event classifier pipeline.

Classifies news items using Gemini, with cross-validation hooks:
- Guard (CC-XVAL-2): Sonnet cross-checks hard-veto Gemini classifications.
- Near-Miss (CC-XVAL-3): Async keyword-triggered Sonnet check on non-veto items.
"""

import asyncio
import logging

from market_engine.config import (
    NEWS_XVAL_GUARD_ENABLED,
    NEWS_XVAL_NEARMISS_ENABLED,
)
from market_engine.llm.taxonomy import HARD_VETO_LEAF_CATEGORIES

logger = logging.getLogger(__name__)


async def _safe_nearmiss(
    news_item_id: int,
    raw_text: str,
    category: str,
    tickers: list[str],
    db,
) -> None:
    """Fire-and-forget near-miss check. Never raises."""
    try:
        from market_engine.llm.nearmiss_checker import check_nearmiss

        await check_nearmiss(news_item_id, raw_text, category, tickers, db)
    except Exception as e:
        logger.warning(f"Near-miss check failed for news_item {news_item_id}: {e}")


async def classify_news_event(
    news_item_id: int,
    raw_text: str,
    db,
    *,
    gemini_category: str = "other",
    gemini_tickers: list[str] | None = None,
) -> dict:
    """Classify a news event and run cross-validation hooks.

    Args:
        news_item_id: ID from news_items table.
        raw_text: Original news text.
        db: Database connection.
        gemini_category: Gemini's classification result.
        gemini_tickers: Tickers Gemini associated with the item.

    Returns:
        Classification result dict.
    """
    tickers = gemini_tickers or []

    result = {
        "news_item_id": news_item_id,
        "category": gemini_category,
        "tickers": tickers,
        "guard_result": None,
        "nearmiss_scheduled": False,
    }

    # === Guard check (synchronous — affects pipeline decision) ===
    if NEWS_XVAL_GUARD_ENABLED and gemini_category in HARD_VETO_LEAF_CATEGORIES:
        try:
            from market_engine.llm.veto_guard import check_guard

            guard_result = await check_guard(
                news_item_id, raw_text, gemini_category, tickers, db
            )
            result["guard_result"] = guard_result
        except Exception as e:
            logger.error(f"Guard check failed: {e}")

    # === Near-Miss (async, non-blocking) ===
    if NEWS_XVAL_NEARMISS_ENABLED and gemini_category not in HARD_VETO_LEAF_CATEGORIES:
        try:
            asyncio.create_task(
                _safe_nearmiss(news_item_id, raw_text, gemini_category, tickers, db)
            )
            result["nearmiss_scheduled"] = True
        except Exception:
            pass  # Never block pipeline

    return result
