"""Baseline Item extractor mirroring current production regex behavior."""

import logging
import re

logger = logging.getLogger(__name__)

_ITEM_PATTERN = re.compile(r"Item\s+(\d+\.\d+)")


def extract_items_regex(html: str) -> list[str]:
    """Extract 8-K Item numbers using the naïve production regex.

    Intentionally permissive — matches all occurrences including TOC and
    citation references, mirroring current production behavior.

    Args:
        html: Raw HTML (or text) of the filing body.

    Returns:
        Sorted unique list of item strings like ["2.02", "9.01"].
    """
    matches = _ITEM_PATTERN.findall(html)
    unique = sorted(set(matches))
    logger.debug("regex parser found %d unique items: %s", len(unique), unique)
    return unique
