"""Tests for the disagreement classifier."""

import pytest

from sec_8k_audit.comparator import classify_disagreement
from sec_8k_audit.item_rules import Category


def _dr(category: Category, hard_veto: bool) -> dict:
    return {
        "category": category,
        "hard_veto_eligible": hard_veto,
        "routing": "rules_engine" if hard_veto else "conditional",
        "primary_item": "4.02",
        "all_items": ["4.02"],
        "rationale": "test",
    }


def test_disagreement_concordance():
    dr = _dr(Category.EARNINGS_RELEASE, False)
    result = classify_disagreement(
        prod_category=str(Category.EARNINGS_RELEASE),
        prod_hard_veto=False,
        dr_classification=dr,
    )
    assert result == "CONCORDANCE"


def test_disagreement_false_negative():
    """Production missed a hard-veto event the DR parser found."""
    dr = _dr(Category.REGULATORY_FORMAL_ACTION, True)
    result = classify_disagreement(
        prod_category=str(Category.NON_EVENT_METADATA),
        prod_hard_veto=False,
        dr_classification=dr,
    )
    assert result == "FALSE_NEGATIVE"


def test_disagreement_false_positive():
    """Production triggered hard-veto but DR says it should not."""
    dr = _dr(Category.NON_EVENT_METADATA, False)
    result = classify_disagreement(
        prod_category=str(Category.REGULATORY_FORMAL_ACTION),
        prod_hard_veto=True,
        dr_classification=dr,
    )
    assert result == "FALSE_POSITIVE"


def test_disagreement_prod_unknown():
    dr = _dr(Category.EARNINGS_RELEASE, False)
    result = classify_disagreement(
        prod_category=None,
        prod_hard_veto=None,
        dr_classification=dr,
    )
    assert result == "PROD_UNKNOWN"
