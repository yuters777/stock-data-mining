"""DR-corrected Item risk rules and filing classifier."""

from __future__ import annotations

import logging
from enum import Enum
from typing import TypedDict

logger = logging.getLogger(__name__)


class Category(str, Enum):
    REGULATORY_FORMAL_ACTION = "REGULATORY_FORMAL_ACTION"
    CYBERSECURITY_INCIDENT = "CYBERSECURITY_INCIDENT"
    EARNINGS_RELEASE = "EARNINGS_RELEASE"
    MATERIAL_AGREEMENT = "MATERIAL_AGREEMENT"
    EXECUTIVE_CHANGE = "EXECUTIVE_CHANGE"
    FINANCIAL_OBLIGATION = "FINANCIAL_OBLIGATION"
    REG_FD_DISCLOSURE = "REG_FD_DISCLOSURE"
    OTHER_EVENT = "OTHER_EVENT"
    NON_EVENT_METADATA = "NON_EVENT_METADATA"


class ItemRule(TypedDict):
    category: Category
    hard_veto_eligible: bool
    routing: str
    rationale: str


ITEM_RULES: dict[str, ItemRule] = {
    # Hard-veto eligible
    "1.03": ItemRule(
        category=Category.REGULATORY_FORMAL_ACTION,
        hard_veto_eligible=True,
        routing="rules_engine",
        rationale="Bankruptcy/Receivership — critical material event",
    ),
    "1.05": ItemRule(
        category=Category.CYBERSECURITY_INCIDENT,
        hard_veto_eligible=True,
        routing="rules_engine",
        rationale="SEC mandates material cybersecurity incident disclosure (2023+). Definition includes materiality test.",
    ),
    "3.01": ItemRule(
        category=Category.REGULATORY_FORMAL_ACTION,
        hard_veto_eligible=True,
        routing="rules_engine",
        rationale="Delisting notice. CAR -1.8% 2d, -11.5% 30d lead-up (N=833 study).",
    ),
    "4.02": ItemRule(
        category=Category.REGULATORY_FORMAL_ACTION,
        hard_veto_eligible=True,
        routing="rules_engine",
        rationale="Non-reliance on financials (restatement). CAR -1.1% d1, -2% 20d (N=8,143 Lerman & Livnat 2009).",
    ),
    # Earnings subsystem — corrected per DR Q3
    "2.02": ItemRule(
        category=Category.EARNINGS_RELEASE,
        hard_veto_eligible=False,
        routing="earnings_subsystem",
        rationale="Earnings release/exhibit. Cannot downgrade by title only — actual content in Exhibit 99.1.",
    ),
    # Conditional
    "1.01": ItemRule(
        category=Category.MATERIAL_AGREEMENT,
        hard_veto_eligible=False,
        routing="conditional",
        rationale="Material agreement scope varies.",
    ),
    "1.02": ItemRule(
        category=Category.MATERIAL_AGREEMENT,
        hard_veto_eligible=False,
        routing="conditional",
        rationale="Material agreement termination — significance varies.",
    ),
    "4.01": ItemRule(
        category=Category.REGULATORY_FORMAL_ACTION,
        hard_veto_eligible=False,
        routing="conditional",
        rationale=(
            "Auditor change. CORRECTED PER DR Q3: range from routine rotation to serious disagreement. "
            "Body must indicate disagreements/reportable events for hard-veto. Auto-veto creates over-veto risk."
        ),
    ),
    "5.02": ItemRule(
        category=Category.EXECUTIVE_CHANGE,
        hard_veto_eligible=False,
        routing="conditional",
        rationale="CEO/CFO matters more than VP.",
    ),
    "7.01": ItemRule(
        category=Category.REG_FD_DISCLOSURE,
        hard_veto_eligible=False,
        routing="conditional",
        rationale="Reg FD disclosure — voluntary, often Q&A. Occasionally material.",
    ),
    "8.01": ItemRule(
        category=Category.OTHER_EVENT,
        hard_veto_eligible=False,
        routing="conditional",
        rationale="Catch-all category. Body required to classify.",
    ),
    # Metadata only
    "5.07": ItemRule(
        category=Category.NON_EVENT_METADATA,
        hard_veto_eligible=False,
        routing="metadata",
        rationale="Shareholder vote — procedural.",
    ),
    "9.01": ItemRule(
        category=Category.NON_EVENT_METADATA,
        hard_veto_eligible=False,
        routing="metadata",
        rationale="Exhibits — metadata only.",
    ),
}


def _default_rule(item: str) -> ItemRule:
    return ItemRule(
        category=Category.OTHER_EVENT,
        hard_veto_eligible=False,
        routing="conditional",
        rationale=f"standard 8-K Item {item}",
    )


def _get_priority(item: str) -> int:
    """Return priority score for item selection (higher wins)."""
    rule = ITEM_RULES.get(item, _default_rule(item))
    if rule["hard_veto_eligible"]:
        return 3
    if rule["routing"] == "earnings_subsystem":
        return 2
    if rule["routing"] == "conditional":
        return 1
    return 0  # metadata


def classify_filing(items: list[str], body_text: str | None = None) -> dict:
    """Classify a filing based on extracted Item numbers.

    Args:
        items: List of item number strings extracted from the filing.
        body_text: Optional body text for future body-based enrichment.

    Returns:
        Dict with keys: category, hard_veto_eligible, routing, primary_item,
        all_items, rationale.
    """
    if not items:
        return {
            "category": Category.NON_EVENT_METADATA,
            "hard_veto_eligible": False,
            "routing": "no_items_extracted",
            "primary_item": None,
            "all_items": [],
            "rationale": "No Items extracted from filing.",
        }

    primary_item = max(items, key=_get_priority)
    rule = ITEM_RULES.get(primary_item, _default_rule(primary_item))

    return {
        "category": rule["category"],
        "hard_veto_eligible": rule["hard_veto_eligible"],
        "routing": rule["routing"],
        "primary_item": primary_item,
        "all_items": sorted(items),
        "rationale": rule["rationale"],
    }
