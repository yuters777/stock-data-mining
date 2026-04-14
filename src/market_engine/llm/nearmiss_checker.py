"""
Near-Miss Checker: async keyword-triggered Sonnet verification of non-veto items.

Catches false negatives — items Gemini classified as non-veto that may actually
contain hard-veto-eligible content.

Spec: LLM_Cross_Validation_Layer_Spec_v1_1.md, Section 5
"""

import logging
import re
import time
from typing import Optional

from market_engine.llm.ab_logger import log_ab_comparison
from market_engine.llm.taxonomy import HARD_VETO_LEAF_CATEGORIES
from market_engine.llm.veto_guard import sonnet_classify
from market_engine.llm.xval_budget import XvalBudget
from market_engine.tickers import TRACKED_TICKERS

logger = logging.getLogger(__name__)

# ── Keyword families (Section 5.4) ───────────────────────────────────────────

NEARMISS_KEYWORDS: dict[str, list[str]] = {
    "earnings_negative": [
        "missed estimates",
        "below expectations",
        "earnings miss",
        "lowered guidance",
        "cut guidance",
        "reduced outlook",
        "profit warning",
        "revenue miss",
        "EPS miss",
        "fell short",
        "withdraws guidance",
        "suspends outlook",
        "preannounces below",
    ],
    "regulatory": [
        "SEC charges",
        "SEC investigation",
        "regulatory action",
        "enforcement action",
        "consent decree",
    ],
}

# Pre-compile regex patterns for each keyword (case-insensitive)
_KEYWORD_PATTERNS: dict[str, list[re.Pattern]] = {
    family: [re.compile(re.escape(kw), re.IGNORECASE) for kw in keywords]
    for family, keywords in NEARMISS_KEYWORDS.items()
}


def scan_keywords(text: str) -> dict[str, list[str]]:
    """Scan text for near-miss keyword matches.

    Returns:
        Dict mapping family name -> list of matched keywords.
        Empty dict if no matches.
    """
    matches: dict[str, list[str]] = {}
    for family, patterns in _KEYWORD_PATTERNS.items():
        family_matches = []
        for pattern, keyword in zip(patterns, NEARMISS_KEYWORDS[family]):
            if pattern.search(text):
                family_matches.append(keyword)
        if family_matches:
            matches[family] = family_matches
    return matches


def compute_priority(
    keyword_matches: dict[str, list[str]],
    tickers: list[str],
    source: str = "",
) -> int:
    """Compute selection priority score for a keyword-hit item.

    Higher score = higher priority for Sonnet checking.

    Priority rules:
    1. Multi-keyword-family matches first (items matching BOTH families)
    2. Items mentioning tracked tickers
    3. EDGAR/RSS sources over Telegram (higher credibility)
    """
    score = 0
    # Multi-family bonus (matches from 2+ families)
    if len(keyword_matches) >= 2:
        score += 100
    # Total keyword count
    total_kw = sum(len(v) for v in keyword_matches.values())
    score += total_kw * 10
    # Tracked ticker bonus
    for t in tickers:
        if t.upper() in TRACKED_TICKERS:
            score += 20
    # Source credibility
    source_lower = source.lower()
    if "edgar" in source_lower:
        score += 30
    elif "rss" in source_lower:
        score += 15
    # Telegram gets no bonus (lowest credibility tier)
    return score


async def check_nearmiss(
    news_item_id: int,
    raw_text: str,
    gemini_category: str,
    gemini_tickers: list[str],
    db,
    *,
    source: str = "",
) -> Optional[dict]:
    """Near-miss check: keyword scan + conditional Sonnet classification.

    Called AFTER Gemini classification, only for non-veto items.

    Args:
        news_item_id: FK to news_items.id.
        raw_text: Original news text.
        gemini_category: Gemini's classification (should NOT be hard-veto).
        gemini_tickers: Tickers Gemini associated with the item.
        db: Database connection.
        source: News source identifier (e.g., 'edgar', 'telegram', 'rss').

    Returns:
        Comparison result dict if Sonnet was called, None otherwise.
    """
    # Safety: skip if already a hard-veto category (Guard handles those)
    if gemini_category in HARD_VETO_LEAF_CATEGORIES:
        return None

    # Step 1: keyword scan
    keyword_matches = scan_keywords(raw_text)
    if not keyword_matches:
        return None

    families_str = ",".join(sorted(keyword_matches.keys()))

    # Step 2: budget check
    budget = XvalBudget(db)
    allowed, reason = await budget.can_call_nearmiss()
    if not allowed:
        logger.info(
            f"Near-miss keyword hit but budget exhausted ({reason}) "
            f"for news_item {news_item_id}"
        )
        await log_ab_comparison(
            db,
            news_item_id=news_item_id,
            gemini_category=gemini_category,
            sonnet_category="nearmiss_keyword_hit_unchecked",
            policy_agreement=True,  # Assume agreement when unchecked
            xval_type="nearmiss",
            keyword_families=families_str,
            error_class=reason,
        )
        return {"status": "unchecked", "reason": reason}

    # Step 3: Sonnet independent classification
    start_ms = time.monotonic_ns() // 1_000_000
    ticker = gemini_tickers[0] if gemini_tickers else ""
    result = await sonnet_classify(raw_text, ticker)
    latency_ms = (time.monotonic_ns() // 1_000_000) - start_ms

    sonnet_cat = result.get("category", "error")
    sonnet_is_veto = sonnet_cat in HARD_VETO_LEAF_CATEGORIES
    # For near-miss, policy agreement means both agree it's NOT veto-eligible
    # (Gemini said non-veto; if Sonnet also says non-veto, they agree)
    agreement = not sonnet_is_veto

    # If Sonnet found a hard-veto category, this is a potential false negative
    sampling_bucket = "P1" if sonnet_is_veto else ""

    await log_ab_comparison(
        db,
        news_item_id=news_item_id,
        gemini_category=gemini_category,
        sonnet_category=sonnet_cat,
        policy_agreement=agreement,
        xval_type="nearmiss",
        sampling_bucket=sampling_bucket,
        sonnet_latency_ms=latency_ms,
        raw_sonnet_response=result.get("reasoning", ""),
        keyword_families=families_str,
    )

    return {
        "status": "checked",
        "sonnet_category": sonnet_cat,
        "agreement": agreement,
        "latency_ms": latency_ms,
        "keyword_families": families_str,
        "false_negative": sonnet_is_veto,
    }


async def batch_check_nearmiss(
    items: list[dict],
    db,
) -> list[dict]:
    """Check multiple keyword-hit items with priority-based selection.

    Used when multiple items hit keywords in one cycle but daily cap limits
    how many can be Sonnet-checked.

    Args:
        items: List of dicts with keys:
            news_item_id, raw_text, gemini_category, gemini_tickers, source
        db: Database connection.

    Returns:
        List of result dicts (checked + unchecked).
    """
    # Score and sort by priority
    scored: list[tuple[int, dict]] = []
    for item in items:
        kw_matches = scan_keywords(item["raw_text"])
        if kw_matches:
            score = compute_priority(
                kw_matches,
                item.get("gemini_tickers", []),
                item.get("source", ""),
            )
            scored.append((score, item))

    # Sort descending by priority score
    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for _score, item in scored:
        result = await check_nearmiss(
            news_item_id=item["news_item_id"],
            raw_text=item["raw_text"],
            gemini_category=item["gemini_category"],
            gemini_tickers=item.get("gemini_tickers", []),
            db=db,
            source=item.get("source", ""),
        )
        if result:
            results.append(result)
    return results
