"""
Audit Plane: nightly stratified Sonnet cross-validation of Gemini classifications.

P0-P2 are mandatory (reuse existing Guard/Near-Miss results — no new API calls).
P3 = stratified random sample with new Sonnet calls (discretionary, budget-gated).

Spec: LLM_Cross_Validation_Layer_Spec_v1_1.md, Section 4
"""

import logging
import random
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_engine.config import (
    NEWS_XVAL_AUDIT_DAILY_DISC_CAP,
    NEWS_XVAL_AUDIT_ENABLED,
)
from market_engine.llm.ab_logger import log_ab_comparison
from market_engine.llm.taxonomy import HARD_VETO_LEAF_CATEGORIES
from market_engine.llm.veto_guard import sonnet_classify
from market_engine.llm.xval_budget import XvalBudget

logger = logging.getLogger(__name__)

TZ_JERUSALEM = ZoneInfo("Asia/Jerusalem")

# ── P3 stratification weights ────────────────────────────────────────────────

SOURCE_WEIGHTS: dict[str, float] = {
    "edgar": 3.0,
    "telegram": 1.0,
    "rss": 0.5,
}

CATEGORY_RARITY_WEIGHTS: dict[str, float] = {
    # Hard-veto eligible → highest sampling weight
    **{cat: 5.0 for cat in HARD_VETO_LEAF_CATEGORIES},
    # Rare soft categories
    "analyst_downgrade": 2.0,
    "sector_rotation": 2.0,
    # Common categories get default 1.0
}

TEXT_LENGTH_ANOMALY_THRESHOLD_LOW = 30  # words
TEXT_LENGTH_ANOMALY_THRESHOLD_HIGH = 500  # words
TEXT_LENGTH_ANOMALY_WEIGHT = 2.0


def _24h_ago_ts() -> int:
    """Return Unix timestamp for 24 hours ago."""
    return int((datetime.now(TZ_JERUSALEM) - timedelta(hours=24)).timestamp())


def compute_p3_weight(
    category: str,
    source: str,
    text: str,
) -> float:
    """Compute stratification weight for a P3 candidate.

    Higher weight = more likely to be sampled.
    """
    weight = 1.0
    # Source weight
    source_lower = source.lower()
    for src_key, src_weight in SOURCE_WEIGHTS.items():
        if src_key in source_lower:
            weight *= src_weight
            break
    # Category rarity
    weight *= CATEGORY_RARITY_WEIGHTS.get(category, 1.0)
    # Text length anomaly
    word_count = len(text.split())
    if word_count < TEXT_LENGTH_ANOMALY_THRESHOLD_LOW or word_count > TEXT_LENGTH_ANOMALY_THRESHOLD_HIGH:
        weight *= TEXT_LENGTH_ANOMALY_WEIGHT
    return weight


async def _tag_bucket(db, news_item_id: int, bucket: str) -> None:
    """Update sampling_bucket for an existing llm_ab_comparison row."""
    try:
        await db.execute(
            """
            UPDATE llm_ab_comparison
            SET sampling_bucket = ?
            WHERE news_item_id = ? AND sampling_bucket = ''
            """,
            (bucket, news_item_id),
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to tag bucket for news_item {news_item_id}: {e}")


async def _get_p0_items(db, since_ts: int) -> list[dict]:
    """P0: Guard disagreements + errors from last 24h."""
    cursor = await db.execute(
        """
        SELECT news_item_id, gemini_category, sonnet_category,
               policy_agreement, error_class
        FROM llm_ab_comparison
        WHERE xval_type = 'guard'
          AND created_at >= ?
          AND (policy_agreement = 0 OR error_class IS NOT NULL)
        """,
        (since_ts,),
    )
    rows = await cursor.fetchall()
    return [
        {
            "news_item_id": r[0],
            "gemini_category": r[1],
            "sonnet_category": r[2],
            "policy_agreement": bool(r[3]),
            "error_class": r[4],
            "bucket": "P0",
        }
        for r in rows
    ]


async def _get_p1_items(db, since_ts: int) -> list[dict]:
    """P1: Near-miss positives + fallback-origin from last 24h."""
    cursor = await db.execute(
        """
        SELECT news_item_id, gemini_category, sonnet_category, policy_agreement
        FROM llm_ab_comparison
        WHERE created_at >= ?
          AND (
            (xval_type = 'nearmiss' AND sonnet_category IN ({placeholders}))
            OR xval_type = 'fallback_unvalidated'
          )
        """.format(
            placeholders=",".join("?" for _ in HARD_VETO_LEAF_CATEGORIES)
        ),
        (since_ts, *sorted(HARD_VETO_LEAF_CATEGORIES)),
    )
    rows = await cursor.fetchall()
    return [
        {
            "news_item_id": r[0],
            "gemini_category": r[1],
            "sonnet_category": r[2],
            "policy_agreement": bool(r[3]),
            "bucket": "P1",
        }
        for r in rows
    ]


async def _get_p2_items(db, since_ts: int) -> list[dict]:
    """P2: Confirmed Guard events (agreement=True) from last 24h."""
    cursor = await db.execute(
        """
        SELECT news_item_id, gemini_category, sonnet_category
        FROM llm_ab_comparison
        WHERE xval_type = 'guard'
          AND created_at >= ?
          AND policy_agreement = 1
          AND error_class IS NULL
        """,
        (since_ts,),
    )
    rows = await cursor.fetchall()
    return [
        {
            "news_item_id": r[0],
            "gemini_category": r[1],
            "sonnet_category": r[2],
            "bucket": "P2",
        }
        for r in rows
    ]


async def _get_p3_candidates(db, since_ts: int) -> list[dict]:
    """P3 candidates: news items NOT already in Guard/Near-Miss results."""
    # Get IDs already covered by Guard/Near-Miss
    cursor = await db.execute(
        """
        SELECT DISTINCT news_item_id FROM llm_ab_comparison
        WHERE created_at >= ?
        """,
        (since_ts,),
    )
    covered_rows = await cursor.fetchall()
    covered_ids = {r[0] for r in covered_rows}

    # Get all news items from last 24h
    cursor = await db.execute(
        """
        SELECT id, raw_text, gemini_category, source, story_group_id
        FROM news_items
        WHERE created_at >= ?
        """,
        (since_ts,),
    )
    rows = await cursor.fetchall()

    # Filter out already-covered items and dedup by story_group_id
    seen_stories: set[int] = set()
    candidates = []
    for r in rows:
        item_id, raw_text, category, source, story_group = r
        if item_id in covered_ids:
            continue
        # Dedup: one item per original story
        if story_group and story_group in seen_stories:
            continue
        if story_group:
            seen_stories.add(story_group)
        candidates.append(
            {
                "news_item_id": item_id,
                "raw_text": raw_text or "",
                "gemini_category": category or "other",
                "source": source or "",
            }
        )
    return candidates


async def _run_p3_sample(db, candidates: list[dict], budget: XvalBudget) -> list[dict]:
    """Run stratified random P3 sample with budget gating.

    Returns list of result dicts for sampled items.
    """
    if not candidates:
        return []

    # Compute weights for weighted random sampling
    weights = [
        compute_p3_weight(c["gemini_category"], c["source"], c["raw_text"])
        for c in candidates
    ]

    # Cap at daily discretionary cap
    max_samples = min(len(candidates), NEWS_XVAL_AUDIT_DAILY_DISC_CAP)

    # Weighted sample without replacement
    if len(candidates) <= max_samples:
        sampled = list(candidates)
    else:
        sampled = []
        remaining = list(zip(candidates, weights))
        for _ in range(max_samples):
            if not remaining:
                break
            items, w = zip(*remaining)
            total_w = sum(w)
            if total_w <= 0:
                break
            probs = [wi / total_w for wi in w]
            # Use random.choices with weights then take unique
            chosen_idx = random.choices(range(len(items)), weights=probs, k=1)[0]
            sampled.append(items[chosen_idx])
            remaining.pop(chosen_idx)

    results = []
    for item in sampled:
        # Budget gate each call
        allowed, reason = await budget.can_call_audit_p3()
        if not allowed:
            logger.info(f"P3 audit budget exhausted ({reason}), stopping.")
            break

        start_ms = time.monotonic_ns() // 1_000_000
        sonnet_result = await sonnet_classify(item["raw_text"])
        latency_ms = (time.monotonic_ns() // 1_000_000) - start_ms

        sonnet_cat = sonnet_result.get("category", "error")
        sonnet_is_veto = sonnet_cat in HARD_VETO_LEAF_CATEGORIES
        gemini_is_veto = item["gemini_category"] in HARD_VETO_LEAF_CATEGORIES
        agreement = sonnet_is_veto == gemini_is_veto

        await log_ab_comparison(
            db,
            news_item_id=item["news_item_id"],
            gemini_category=item["gemini_category"],
            sonnet_category=sonnet_cat,
            policy_agreement=agreement,
            xval_type="audit",
            sampling_bucket="P3",
            sonnet_latency_ms=latency_ms,
            raw_sonnet_response=sonnet_result.get("reasoning", ""),
        )

        results.append(
            {
                "news_item_id": item["news_item_id"],
                "sonnet_category": sonnet_cat,
                "agreement": agreement,
                "bucket": "P3",
            }
        )

    return results


async def run_nightly_audit(db) -> dict:
    """Run nightly audit at 04:00 Asia/Jerusalem.

    Returns summary dict with counts per bucket, agreement rates, alerts sent.
    """
    if not NEWS_XVAL_AUDIT_ENABLED:
        return {"status": "disabled"}

    since_ts = _24h_ago_ts()
    budget = XvalBudget(db)

    # P0: Guard disagreements + errors (reuse existing — no new API calls)
    p0_items = await _get_p0_items(db, since_ts)
    for item in p0_items:
        await _tag_bucket(db, item["news_item_id"], "P0")

    # P1: Near-miss positives + fallback (reuse existing — no new API calls)
    p1_items = await _get_p1_items(db, since_ts)
    for item in p1_items:
        await _tag_bucket(db, item["news_item_id"], "P1")

    # P2: Confirmed Guard events (reuse existing — no new API calls)
    p2_items = await _get_p2_items(db, since_ts)
    for item in p2_items:
        await _tag_bucket(db, item["news_item_id"], "P2")

    # P3: Stratified random sample (NEW Sonnet calls, budget-gated)
    p3_candidates = await _get_p3_candidates(db, since_ts)
    p3_results = await _run_p3_sample(db, p3_candidates, budget)

    # Count disagreements for alerting
    p0_disagreements = [i for i in p0_items if not i.get("policy_agreement", True)]
    p3_disagreements = [r for r in p3_results if not r["agreement"]]

    alerts_sent = 0
    # P0-P2 disagreements get immediate alert
    if p0_disagreements:
        alert_msg = (
            f"XVAL ALERT: {len(p0_disagreements)} Guard disagreement(s) in last 24h. "
            f"Review P0 items."
        )
        logger.warning(alert_msg)
        alerts_sent += 1

    if p3_disagreements:
        alert_msg = (
            f"XVAL ALERT: {len(p3_disagreements)} P3 audit disagreement(s) found."
        )
        logger.warning(alert_msg)
        alerts_sent += 1

    summary = {
        "status": "completed",
        "p0_count": len(p0_items),
        "p1_count": len(p1_items),
        "p2_count": len(p2_items),
        "p3_sampled": len(p3_results),
        "p3_candidates": len(p3_candidates),
        "p0_disagreements": len(p0_disagreements),
        "p3_disagreements": len(p3_disagreements),
        "p3_agreement_rate": (
            round(
                (len(p3_results) - len(p3_disagreements)) / len(p3_results), 3
            )
            if p3_results
            else None
        ),
        "alerts_sent": alerts_sent,
    }

    logger.info(f"Nightly audit complete: {summary}")
    return summary


async def run_weekly_summary(db) -> str:
    """Generate weekly summary for Telegram. Runs Sunday 08:00 Asia/Jerusalem."""
    now = datetime.now(TZ_JERUSALEM)
    week_start = now - timedelta(days=7)
    week_start_ts = int(week_start.timestamp())

    # Query weekly stats
    cursor = await db.execute(
        """
        SELECT xval_type, COUNT(*) as cnt,
               SUM(CASE WHEN policy_agreement = 1 THEN 1 ELSE 0 END) as agree_cnt,
               SUM(CASE WHEN policy_agreement = 0 THEN 1 ELSE 0 END) as disagree_cnt
        FROM llm_ab_comparison
        WHERE created_at >= ?
        GROUP BY xval_type
        """,
        (week_start_ts,),
    )
    rows = await cursor.fetchall()
    stats: dict[str, dict[str, int]] = {}
    for r in rows:
        stats[r[0]] = {"total": r[1], "agree": r[2], "disagree": r[3]}

    # Budget status
    budget = XvalBudget(db)
    budget_status = await budget.get_status()

    # Pending verdicts (P0/P1 items without resolution)
    cursor = await db.execute(
        """
        SELECT COUNT(*) FROM llm_ab_comparison
        WHERE sampling_bucket IN ('P0', 'P1')
          AND created_at >= ?
          AND policy_agreement = 0
        """,
        (week_start_ts,),
    )
    pending_row = await cursor.fetchone()
    pending = pending_row[0] if pending_row else 0

    # Format dates
    week_start_str = week_start.strftime("%b %d")
    week_end_str = now.strftime("%b %d")

    guard = stats.get("guard", {"total": 0, "agree": 0, "disagree": 0})
    audit = stats.get("audit", {"total": 0, "agree": 0, "disagree": 0})
    nearmiss = stats.get("nearmiss", {"total": 0, "agree": 0, "disagree": 0})

    # Count near-miss false negatives
    cursor = await db.execute(
        """
        SELECT COUNT(*) FROM llm_ab_comparison
        WHERE xval_type = 'nearmiss'
          AND created_at >= ?
          AND policy_agreement = 0
        """,
        (week_start_ts,),
    )
    nm_fn_row = await cursor.fetchone()
    nm_false_negatives = nm_fn_row[0] if nm_fn_row else 0

    cost_pct = (
        round(budget_status["week_cost_usd"] / budget_status["ceiling_usd"] * 100)
        if budget_status["ceiling_usd"] > 0
        else 0
    )

    summary = (
        f"XVAL Weekly Summary ({week_start_str}-{week_end_str}):\n"
        f"Guard: {guard['total']} events "
        f"({guard['agree']} confirmed, {guard['disagree']} disagreed)\n"
        f"Audit: {audit['total']} sampled "
        f"({audit['agree']} agree, {audit['disagree']} disagree)\n"
        f"Near-Miss: {nearmiss['total']} checked "
        f"({nm_false_negatives} false negatives found)\n"
        f"Budget: ${budget_status['week_cost_usd']:.2f} / "
        f"${budget_status['ceiling_usd']:.2f} ({cost_pct}%)\n"
        f"Pending verdicts: {pending}"
    )

    logger.info(f"Weekly summary:\n{summary}")
    return summary


async def maybe_run_weekly(db) -> str | None:
    """Check if today is Sunday and run weekly summary if so."""
    now = datetime.now(TZ_JERUSALEM)
    if now.weekday() == 6:  # Sunday
        return await run_weekly_summary(db)
    return None
