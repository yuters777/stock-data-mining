"""
Veto Guard — Sonnet cross-validation of Gemini hard-veto classifications.

When Gemini classifies a news item as a hard-veto category, Guard independently
asks Sonnet to classify the same raw text. If they disagree, the item is flagged.

CC-XVAL-2 module. Guard calls use the reserved budget tier.
"""

import asyncio
import logging
import time

from market_engine.config import NEWS_XVAL_GUARD_ENABLED
from market_engine.llm.taxonomy import (
    CATEGORY_DEFINITIONS,
    HARD_VETO_LEAF_CATEGORIES,
    TAXONOMY_VERSION,
)
from market_engine.llm.ab_logger import log_ab_comparison

logger = logging.getLogger(__name__)

# Concurrency control for Guard Sonnet calls
_guard_semaphore = asyncio.Semaphore(2)


async def sonnet_classify(raw_text: str, ticker: str = "") -> dict:
    """Independently classify news text using Sonnet.

    Sends raw text + taxonomy to Sonnet (no Gemini output).
    Returns dict with 'category', 'confidence', 'reasoning'.

    This function is shared by Guard, Near-Miss, and Audit P3.
    Guard uses _guard_semaphore externally; others do not.
    """
    categories_list = ", ".join(sorted(CATEGORY_DEFINITIONS.keys()))
    prompt = (
        f"Classify this news event into exactly one category.\n"
        f"Valid categories: {categories_list}\n"
        f"Taxonomy version: {TAXONOMY_VERSION}\n"
        f"{'Ticker: ' + ticker if ticker else ''}\n\n"
        f"News text:\n{raw_text}\n\n"
        f"Respond with JSON: {{\"category\": \"...\", \"confidence\": 0.0-1.0, \"reasoning\": \"...\"}}"
    )
    # In production, this calls the Anthropic API.
    # For now, return a placeholder that tests can mock.
    return {
        "category": "other",
        "confidence": 0.0,
        "reasoning": "placeholder — API not configured",
    }


async def check_guard(
    news_item_id: int,
    raw_text: str,
    gemini_category: str,
    gemini_tickers: list[str],
    db,
) -> dict | None:
    """Guard check: Sonnet cross-validates Gemini hard-veto classification.

    Only called when gemini_category is in HARD_VETO_LEAF_CATEGORIES.
    Returns comparison result dict, or None if disabled/error.
    """
    if not NEWS_XVAL_GUARD_ENABLED:
        return None

    if gemini_category not in HARD_VETO_LEAF_CATEGORIES:
        return None

    start_ms = time.monotonic_ns() // 1_000_000
    try:
        async with _guard_semaphore:
            ticker = gemini_tickers[0] if gemini_tickers else ""
            result = await sonnet_classify(raw_text, ticker)

        latency_ms = (time.monotonic_ns() // 1_000_000) - start_ms
        sonnet_cat = result.get("category", "error")
        sonnet_is_veto = sonnet_cat in HARD_VETO_LEAF_CATEGORIES
        gemini_is_veto = gemini_category in HARD_VETO_LEAF_CATEGORIES
        agreement = sonnet_is_veto == gemini_is_veto

        await log_ab_comparison(
            db,
            news_item_id=news_item_id,
            gemini_category=gemini_category,
            sonnet_category=sonnet_cat,
            policy_agreement=agreement,
            xval_type="guard",
            sampling_bucket="P0" if not agreement else "P2",
            sonnet_latency_ms=latency_ms,
            raw_sonnet_response=result.get("reasoning", ""),
        )

        return {
            "sonnet_category": sonnet_cat,
            "agreement": agreement,
            "latency_ms": latency_ms,
        }

    except Exception as e:
        logger.error(f"Guard check failed for news_item {news_item_id}: {e}")
        await log_ab_comparison(
            db,
            news_item_id=news_item_id,
            gemini_category=gemini_category,
            sonnet_category="error",
            policy_agreement=False,
            xval_type="guard",
            sampling_bucket="P0",
            error_class=type(e).__name__,
        )
        return None
