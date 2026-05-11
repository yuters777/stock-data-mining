"""Compares production classifications against DR-corrected classifications."""

from __future__ import annotations

import logging
import sqlite3
from typing import TypedDict

from .classifier import classify
from .item_parser_regex import extract_items_regex
from .item_parser_structural import extract_items_structural

logger = logging.getLogger(__name__)

_QUERY = """
SELECT
    sf.id,
    sf.accession_number,
    sf.ticker,
    sf.filing_form,
    sf.filing_date,
    sf.primary_doc_url,
    ni.classification_status   AS prod_category,
    ne.hard_veto_status        AS prod_hard_veto,
    ne.category                AS prod_event_category
FROM sec_filings sf
LEFT JOIN news_items  ni ON ni.id         = sf.news_item_id
LEFT JOIN news_events ne ON ne.trace_id   = ni.trace_id
WHERE sf.filing_form IN ('8-K', '8-K/A')
"""


class ComparisonRecord(TypedDict):
    accession_number: str
    ticker: str
    filing_form: str
    filing_date: str
    primary_doc_url: str
    prod_category: str | None
    prod_hard_veto: bool | None
    regex_items: list[str]
    structural_items: list[str]
    dr_classification: dict
    disagreement_type: str


def classify_disagreement(
    prod_category: str | None,
    prod_hard_veto: bool | None,
    dr_classification: dict,
) -> str:
    """Classify the disagreement type between production and DR classification.

    Args:
        prod_category: Production category string or None if unknown.
        prod_hard_veto: Whether production marked this as hard-veto eligible.
        dr_classification: DR classification dict from classifier.classify.

    Returns:
        One of: 'PROD_UNKNOWN', 'FALSE_NEGATIVE', 'FALSE_POSITIVE',
                'CONCORDANCE', 'MATERIALITY_MISS'.
    """
    if prod_category is None:
        return "PROD_UNKNOWN"

    dr_hard_veto = dr_classification["hard_veto_eligible"]

    if not prod_hard_veto and dr_hard_veto:
        return "FALSE_NEGATIVE"
    if prod_hard_veto and not dr_hard_veto:
        return "FALSE_POSITIVE"
    if prod_category == str(dr_classification["category"]):
        return "CONCORDANCE"
    return "MATERIALITY_MISS"


def compare_classifications(
    snapshot_conn: sqlite3.Connection,
    fetched_bodies: dict[str, str],
) -> list[ComparisonRecord]:
    """Iterate all 8-K filings in snapshot and compare classifications.

    Args:
        snapshot_conn: Read-only SQLite connection to the snapshot.
        fetched_bodies: Dict mapping accession_number -> HTML body text.

    Returns:
        List of ComparisonRecord dicts.
    """
    cursor = snapshot_conn.execute(_QUERY)
    rows = cursor.fetchall()
    logger.info("Comparing %d 8-K filing rows from snapshot", len(rows))

    results: list[ComparisonRecord] = []

    for row in rows:
        accession = row["accession_number"]
        body = fetched_bodies.get(accession, "")

        regex_items = extract_items_regex(body) if body else []
        structural_items, _ = extract_items_structural(body) if body else ([], {})
        dr_classification = classify(structural_items, body)

        prod_hard_veto_raw = row["prod_hard_veto"]
        if prod_hard_veto_raw is None:
            prod_hard_veto = None
        else:
            prod_hard_veto = bool(prod_hard_veto_raw)

        prod_category = row["prod_event_category"] or row["prod_category"]

        disagreement = classify_disagreement(prod_category, prod_hard_veto, dr_classification)

        record: ComparisonRecord = {
            "accession_number": accession,
            "ticker": row["ticker"],
            "filing_form": row["filing_form"],
            "filing_date": row["filing_date"],
            "primary_doc_url": row["primary_doc_url"] or "",
            "prod_category": prod_category,
            "prod_hard_veto": prod_hard_veto,
            "regex_items": regex_items,
            "structural_items": structural_items,
            "dr_classification": dr_classification,
            "disagreement_type": disagreement,
        }
        results.append(record)

    logger.info("Comparison complete: %d records", len(results))
    return results
