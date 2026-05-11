"""Thin wrapper combining item extraction with DR-corrected classification."""

from __future__ import annotations

import logging

from .item_rules import classify_filing

logger = logging.getLogger(__name__)


def classify(items: list[str], body: str | None = None) -> dict:
    """Classify a filing given extracted items.

    Args:
        items: Extracted 8-K item number strings.
        body: Optional filing body for enrichment (reserved for future use).

    Returns:
        Classification dict from item_rules.classify_filing.
    """
    return classify_filing(items, body_text=body)
