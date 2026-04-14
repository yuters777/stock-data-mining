"""
Nightly health check — scheduled tasks including XVAL audit.

Runs at 04:00 Asia/Jerusalem. Integrates the audit plane and weekly summary.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from market_engine.config import NEWS_XVAL_AUDIT_ENABLED

logger = logging.getLogger(__name__)

TZ_JERUSALEM = ZoneInfo("Asia/Jerusalem")


async def run_nightly_health(db) -> dict:
    """Run all nightly health checks.

    Args:
        db: Database connection.

    Returns:
        Dict with results from each health check component.
    """
    results: dict = {"timestamp": datetime.now(TZ_JERUSALEM).isoformat()}

    # === XVAL Audit (CC-XVAL-3) ===
    if NEWS_XVAL_AUDIT_ENABLED:
        try:
            from market_engine.llm.xval_auditor import (
                run_nightly_audit,
                maybe_run_weekly,
            )

            audit_result = await run_nightly_audit(db)
            results["xval_audit"] = audit_result
            logger.info(f"XVAL audit: {audit_result}")

            # Weekly summary (Sunday only)
            weekly = await maybe_run_weekly(db)
            if weekly:
                results["xval_weekly_summary"] = weekly
                logger.info(f"XVAL weekly summary sent")

        except Exception as e:
            logger.error(f"XVAL audit failed: {e}")
            results["xval_audit"] = {"status": "error", "error": str(e)}
    else:
        results["xval_audit"] = {"status": "disabled"}

    return results
