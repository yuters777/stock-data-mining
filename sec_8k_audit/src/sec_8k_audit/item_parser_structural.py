"""DR-recommended structural 8-K Item extractor."""

import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

VALID_8K_ITEMS: frozenset[str] = frozenset({
    "1.01", "1.02", "1.03", "1.04", "1.05",
    "2.01", "2.02", "2.03", "2.04", "2.05", "2.06",
    "3.01", "3.02", "3.03",
    "4.01", "4.02",
    "5.01", "5.02", "5.03", "5.04", "5.05", "5.06", "5.07", "5.08",
    "6.01", "6.02", "6.03", "6.04", "6.05", "6.06",
    "7.01",
    "8.01",
    "9.01",
})

_CITATION_INDICATORS = (
    "pursuant to",
    "as disclosed in",
    "see item",
    "referenced in",
    "previously reported",
    "as filed",
    "incorporated by reference",
)

_STRICT_ITEM_RE = re.compile(
    r"^\s*Item\s+(\d+\.\d+)(?:\s*[\.\:\-\—]|\s*$)",
    re.MULTILINE | re.IGNORECASE,
)

_DOT_LEADER_RE = re.compile(r"\.{3,}|…{2,}")
_PAGE_REF_RE = re.compile(r"\b\d{1,3}\s*$", re.MULTILINE)


def _is_toc_table(table) -> bool:
    """Return True if this <table> looks like a Table of Contents."""
    text = table.get_text(separator=" ")
    item_count = len(re.findall(r"\bItem\s+\d+\.\d+", text, re.IGNORECASE))
    has_dot_leaders = bool(_DOT_LEADER_RE.search(text))
    has_page_refs = bool(_PAGE_REF_RE.search(text))
    return item_count >= 3 and (has_dot_leaders or has_page_refs)


def extract_items_structural(html: str) -> tuple[list[str], dict]:
    """Extract 8-K Item numbers using structure-aware parsing.

    Steps:
      1. Parse with lxml via BeautifulSoup.
      2. Strip <nav> and <header> tags.
      3. Detect and remove TOC tables.
      4. Extract plain text.
      5. Apply strict Item header regex.
      6. Check preceding context for citation indicators.
      7. Validate against VALID_8K_ITEMS.

    Args:
        html: Raw HTML of the filing body.

    Returns:
        Tuple of (declared_items, debug_info).
        declared_items: sorted list of valid item strings.
        debug_info: dict with keys 'declared_count', 'rejected_count', 'rejected_details'.
    """
    rejected_details: list[dict] = []

    if not html or not html.strip():
        return [], {
            "declared_count": 0,
            "rejected_count": 0,
            "rejected_details": rejected_details,
        }

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        logger.warning("HTML parse error: %s", exc)
        return [], {
            "declared_count": 0,
            "rejected_count": 0,
            "rejected_details": rejected_details,
        }

    # Strip navigation and header elements
    for tag in soup.find_all(["nav", "header"]):
        tag.decompose()

    # Remove TOC tables
    for table in soup.find_all("table"):
        if _is_toc_table(table):
            logger.debug("Decomposing TOC table")
            table.decompose()

    text = soup.get_text(separator="\n")

    declared: list[str] = []

    for match in _STRICT_ITEM_RE.finditer(text):
        item_num = match.group(1)
        start = match.start()
        preceding = text[max(0, start - 50): start].lower()

        if any(indicator in preceding for indicator in _CITATION_INDICATORS):
            rejected_details.append({
                "item": item_num,
                "reason": "citation_in_context",
                "context_snippet": text[max(0, start - 50): start + 20],
            })
            continue

        if item_num not in VALID_8K_ITEMS:
            rejected_details.append({
                "item": item_num,
                "reason": "not_valid_8k_item",
                "context_snippet": text[start: start + 40],
            })
            continue

        declared.append(item_num)

    unique_declared = sorted(set(declared))
    debug_info = {
        "declared_count": len(unique_declared),
        "rejected_count": len(rejected_details),
        "rejected_details": rejected_details,
    }
    logger.debug("structural parser: %d declared, %d rejected", len(unique_declared), len(rejected_details))
    return unique_declared, debug_info
