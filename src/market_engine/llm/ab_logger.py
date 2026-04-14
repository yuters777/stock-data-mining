"""
A/B comparison logger — writes cross-validation results to llm_ab_comparison table.

Used by Guard, Audit, and Near-Miss to record Sonnet vs Gemini classification comparisons.
"""

import logging
import time

logger = logging.getLogger(__name__)


async def log_ab_comparison(
    db,
    *,
    news_item_id: int,
    gemini_category: str,
    sonnet_category: str,
    policy_agreement: bool,
    xval_type: str,
    sampling_bucket: str = "",
    error_class: str | None = None,
    sonnet_latency_ms: int = 0,
    raw_sonnet_response: str = "",
    keyword_families: str = "",
):
    """Insert a row into llm_ab_comparison.

    Args:
        db: Database connection (aiosqlite or compatible).
        news_item_id: FK to news_items.id.
        gemini_category: Gemini's classification.
        sonnet_category: Sonnet's independent classification.
        policy_agreement: Whether both models agree on veto/non-veto policy.
        xval_type: One of 'guard', 'audit', 'nearmiss'.
        sampling_bucket: P0-P3 priority tier (for audit).
        error_class: Error type if Sonnet call failed.
        sonnet_latency_ms: Sonnet API call latency in milliseconds.
        raw_sonnet_response: Full Sonnet response text.
        keyword_families: Comma-separated keyword families that triggered near-miss.
    """
    created_at = int(time.time())
    try:
        await db.execute(
            """
            INSERT INTO llm_ab_comparison (
                news_item_id, gemini_category, sonnet_category,
                policy_agreement, xval_type, sampling_bucket,
                error_class, sonnet_latency_ms, raw_sonnet_response,
                keyword_families, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                news_item_id, gemini_category, sonnet_category,
                policy_agreement, xval_type, sampling_bucket,
                error_class, sonnet_latency_ms, raw_sonnet_response,
                keyword_families, created_at,
            ),
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to log AB comparison: {e}")
