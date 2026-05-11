"""Tests for the structural 8-K Item parser."""

from pathlib import Path

import pytest

from sec_8k_audit.item_parser_structural import extract_items_structural

FIXTURES = Path(__file__).parent / "fixtures" / "sample_8k_bodies"


def _load(filename: str) -> str:
    return (FIXTURES / filename).read_text(encoding="utf-8")


def test_extracts_declared_items_4_02_filing():
    html = _load("sample_4_02_restatement.html")
    items, _ = extract_items_structural(html)
    assert "4.02" in items


def test_rejects_citation_references():
    """Item 7.01 appears only in a citation phrase — must be rejected."""
    html = _load("sample_4_02_restatement.html")
    items, _ = extract_items_structural(html)
    assert "7.01" not in items


def test_strips_toc_table():
    """Item 5.02 should appear exactly once despite TOC entry."""
    html = _load("sample_5_02_exec.html")
    items, _ = extract_items_structural(html)
    assert "5.02" in items
    # Verify no duplication from TOC — items list is de-duplicated
    assert items.count("5.02") == 1


def test_multi_item_extraction():
    """Both 4.02 and 9.01 should be extracted from the restatement fixture."""
    html = _load("sample_4_02_restatement.html")
    items, _ = extract_items_structural(html)
    assert "4.02" in items
    assert "9.01" in items


def test_8ka_amendment_parsing():
    """8-K/A amendment body should yield Item 5.02."""
    html = _load("sample_8ka_amendment.html")
    items, _ = extract_items_structural(html)
    assert "5.02" in items


def test_empty_body():
    items, debug = extract_items_structural("")
    assert items == []
    assert debug["declared_count"] == 0


def test_invalid_html():
    """Malformed HTML must not raise — returns empty list."""
    malformed = "<<<<<not html at all!!! Item 99.99 >>> <!--"
    items, debug = extract_items_structural(malformed)
    # Should not crash; 99.99 is not a valid 8-K item so not in result
    assert isinstance(items, list)
    assert "99.99" not in items


def test_debug_info_present():
    html = _load("sample_4_02_restatement.html")
    _, debug = extract_items_structural(html)
    assert "declared_count" in debug
    assert "rejected_count" in debug
    assert "rejected_details" in debug
