"""
Two-tier XVAL budget manager.

Tier 1 (Reserved): Guard calls — never cut, $0.50/week allocation.
Tier 2 (Discretionary): Audit P3 + Near-Miss — cuts first on budget pressure.

Budget resets weekly (Monday 00:00 Asia/Jerusalem).
All costs approximate: ~$0.007 per Sonnet call (input ~500 tokens + output ~200 tokens).
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_engine.config import (
    NEWS_XVAL_AUDIT_DAILY_DISC_CAP,
    NEWS_XVAL_GUARD_RESERVED_BUDGET,
    NEWS_XVAL_NEARMISS_DAILY_CAP,
    NEWS_XVAL_NEARMISS_WEEKLY_CAP,
    NEWS_XVAL_WEEKLY_COST_CEILING,
)

logger = logging.getLogger(__name__)

TZ_JERUSALEM = ZoneInfo("Asia/Jerusalem")


def _week_start_ts() -> int:
    """Return Unix timestamp for Monday 00:00 Asia/Jerusalem of the current ISO week."""
    now = datetime.now(TZ_JERUSALEM)
    # Monday = 0, Sunday = 6
    days_since_monday = now.weekday()
    monday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=days_since_monday
    )
    return int(monday.timestamp())


def _today_start_ts() -> int:
    """Return Unix timestamp for today 00:00 Asia/Jerusalem."""
    now = datetime.now(TZ_JERUSALEM)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(today.timestamp())


class XvalBudget:
    """Track weekly XVAL Sonnet API budget."""

    COST_PER_CALL_USD = 0.007  # Approximate Sonnet call cost

    def __init__(self, db):
        self.db = db
        self.weekly_ceiling = NEWS_XVAL_WEEKLY_COST_CEILING
        self.guard_reserved = NEWS_XVAL_GUARD_RESERVED_BUDGET
        self.audit_daily_cap = NEWS_XVAL_AUDIT_DAILY_DISC_CAP
        self.nearmiss_daily_cap = NEWS_XVAL_NEARMISS_DAILY_CAP
        self.nearmiss_weekly_cap = NEWS_XVAL_NEARMISS_WEEKLY_CAP

    async def get_weekly_usage(self) -> dict[str, int]:
        """Query llm_ab_comparison for current week's Sonnet calls by type.

        Returns:
            Dict mapping xval_type -> call count for current ISO week.
        """
        week_start = _week_start_ts()
        cursor = await self.db.execute(
            """
            SELECT xval_type, COUNT(*) as cnt
            FROM llm_ab_comparison
            WHERE created_at >= ?
              AND xval_type IN ('guard', 'audit', 'nearmiss')
            GROUP BY xval_type
            """,
            (week_start,),
        )
        rows = await cursor.fetchall()
        result: dict[str, int] = {}
        for row in rows:
            result[row[0]] = row[1]
        return result

    async def _count_today(self, xval_type: str) -> int:
        """Count rows in llm_ab_comparison for a given type today (Asia/Jerusalem)."""
        today_start = _today_start_ts()
        cursor = await self.db.execute(
            """
            SELECT COUNT(*) FROM llm_ab_comparison
            WHERE xval_type = ? AND created_at >= ?
            """,
            (xval_type, today_start),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def can_call_guard(self) -> tuple[bool, str]:
        """Guard always allowed unless total ceiling exceeded."""
        usage = await self.get_weekly_usage()
        total_cost = sum(usage.values()) * self.COST_PER_CALL_USD
        if total_cost >= self.weekly_ceiling:
            return False, "weekly_ceiling_exceeded"
        return True, "ok"

    async def can_call_audit_p3(self) -> tuple[bool, str]:
        """Discretionary P3 — daily cap + weekly total check."""
        # Check daily cap
        today_p3 = await self._count_today("audit")
        if today_p3 >= self.audit_daily_cap:
            return False, "daily_audit_cap"
        # Check weekly discretionary budget
        usage = await self.get_weekly_usage()
        total_cost = sum(usage.values()) * self.COST_PER_CALL_USD
        guard_cost = usage.get("guard", 0) * self.COST_PER_CALL_USD
        discretionary_used = total_cost - guard_cost
        discretionary_budget = self.weekly_ceiling - self.guard_reserved
        if discretionary_used >= discretionary_budget:
            return False, "discretionary_exhausted"
        return True, "ok"

    async def can_call_nearmiss(self) -> tuple[bool, str]:
        """Near-miss — daily + weekly caps + discretionary budget."""
        # Daily cap
        today_nm = await self._count_today("nearmiss")
        if today_nm >= self.nearmiss_daily_cap:
            return False, "daily_nearmiss_cap"
        # Weekly cap
        usage = await self.get_weekly_usage()
        week_nm = usage.get("nearmiss", 0)
        if week_nm >= self.nearmiss_weekly_cap:
            return False, "weekly_nearmiss_cap"
        # Discretionary budget check
        total_cost = sum(usage.values()) * self.COST_PER_CALL_USD
        guard_cost = usage.get("guard", 0) * self.COST_PER_CALL_USD
        discretionary_used = total_cost - guard_cost
        discretionary_budget = self.weekly_ceiling - self.guard_reserved
        if discretionary_used >= discretionary_budget:
            return False, "discretionary_exhausted"
        return True, "ok"

    async def get_status(self) -> dict:
        """For /xval_status Telegram command."""
        usage = await self.get_weekly_usage()
        total_calls = sum(usage.values())
        total_cost = total_calls * self.COST_PER_CALL_USD
        guard_cost = usage.get("guard", 0) * self.COST_PER_CALL_USD
        discretionary_used = total_cost - guard_cost
        discretionary_budget = self.weekly_ceiling - self.guard_reserved
        return {
            "week_calls": usage,
            "week_total_calls": total_calls,
            "week_cost_usd": round(total_cost, 3),
            "ceiling_usd": self.weekly_ceiling,
            "guard_reserved_usd": self.guard_reserved,
            "discretionary_remaining_usd": round(
                max(0, discretionary_budget - discretionary_used), 3
            ),
        }
