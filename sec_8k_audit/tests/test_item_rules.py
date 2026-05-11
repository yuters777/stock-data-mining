"""Tests for DR-corrected Item risk rules and classify_filing."""

import pytest

from sec_8k_audit.item_rules import Category, ITEM_RULES, classify_filing


def test_item_1_05_hard_veto():
    assert ITEM_RULES["1.05"]["hard_veto_eligible"] is True


def test_item_4_01_not_hard_veto():
    """DR Q3 correction: auditor change must NOT be auto hard-veto."""
    assert ITEM_RULES["4.01"]["hard_veto_eligible"] is False


def test_item_2_02_earnings_routing():
    assert ITEM_RULES["2.02"]["routing"] == "earnings_subsystem"


def test_multi_item_priority_4_02_wins():
    """4.02 is hard-veto eligible and must beat 9.01 (metadata)."""
    result = classify_filing(["4.02", "9.01"])
    assert result["primary_item"] == "4.02"


def test_multi_item_priority_5_02_over_9_01():
    """5.02 is conditional (priority 1) and beats 9.01 (metadata, priority 0)."""
    result = classify_filing(["5.02", "9.01"])
    assert result["primary_item"] == "5.02"


def test_unknown_item_default_rule():
    """Item not in ITEM_RULES should fall back to default rule, not raise."""
    result = classify_filing(["3.04"])
    assert result["routing"] == "conditional"
    assert result["category"] == Category.OTHER_EVENT


def test_empty_items_no_extraction():
    result = classify_filing([])
    assert result["routing"] == "no_items_extracted"
    assert result["hard_veto_eligible"] is False


def test_all_hard_veto_items():
    hard_veto_set = {"1.03", "1.05", "3.01", "4.02"}
    for item in hard_veto_set:
        assert ITEM_RULES[item]["hard_veto_eligible"] is True, (
            f"Expected {item} to be hard_veto_eligible"
        )
