"""CLI entry point for the SEC 8-K retrospective audit."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from .comparator import compare_classifications
from .edgar_fetcher import fetch_all_bodies
from .report_generator import generate_report
from .snapshot_loader import load_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_FILINGS_QUERY = """
SELECT
    sf.id,
    sf.accession_number,
    sf.ticker,
    sf.filing_form,
    sf.filing_date,
    sf.primary_doc_url
FROM sec_filings sf
WHERE sf.filing_form IN ('8-K', '8-K/A')
  AND sf.primary_doc_url IS NOT NULL
  AND sf.primary_doc_url != ''
"""


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sec_8k_audit",
        description="SEC 8-K retrospective classification audit (Phase B)",
    )
    p.add_argument("--snapshot", required=True, type=Path, help="Path to snapshot .db file")
    p.add_argument("--output", required=True, type=Path, help="Path to write markdown report")
    p.add_argument("--limit", type=int, default=None, help="Limit filings count (dry-run)")
    p.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/bodies"),
        help="Directory for caching fetched filing bodies",
    )
    p.add_argument("--concurrency", type=int, default=5, help="Max concurrent EDGAR fetches")
    return p


def main() -> None:
    """Main CLI entry point."""
    args = _build_parser().parse_args()
    run_start = time.time()

    logger.info("Loading snapshot: %s", args.snapshot)
    conn = load_snapshot(args.snapshot)

    query = _FILINGS_QUERY
    if args.limit:
        query += f" LIMIT {int(args.limit)}"

    rows = conn.execute(query).fetchall()
    filings = [dict(r) for r in rows]
    logger.info("Loaded %d 8-K filings from snapshot", len(filings))

    logger.info("Fetching filing bodies (cache: %s, concurrency: %d)", args.cache_dir, args.concurrency)
    fetched_bodies = asyncio.run(
        fetch_all_bodies(filings, args.cache_dir, concurrency=args.concurrency)
    )
    logger.info("Bodies available: %d / %d", len(fetched_bodies), len(filings))

    logger.info("Running comparator…")
    results = compare_classifications(conn, fetched_bodies)

    snapshot_metadata = {
        "snapshot_path": args.snapshot,
        "snapshot_date": args.snapshot.stem,
        "run_start_time": run_start,
        "total_sec_requests": len(filings) - sum(
            1 for f in filings if (args.cache_dir / f"{f['accession_number']}.html").exists()
        ),
        "cache_dir": args.cache_dir,
    }

    logger.info("Generating report: %s", args.output)
    generate_report(results, args.output, snapshot_metadata)

    from collections import Counter
    counts = Counter(r["disagreement_type"] for r in results)
    print("\n=== SEC 8-K Audit — Phase B Summary ===")
    print(f"  Filings analysed : {len(results)}")
    print(f"  Concordance      : {counts.get('CONCORDANCE', 0)}")
    print(f"  False Negatives  : {counts.get('FALSE_NEGATIVE', 0)}")
    print(f"  False Positives  : {counts.get('FALSE_POSITIVE', 0)}")
    print(f"  Materiality Miss : {counts.get('MATERIALITY_MISS', 0)}")
    print(f"  Prod Unknown     : {counts.get('PROD_UNKNOWN', 0)}")
    print(f"  Report           : {args.output}")
    print(f"  Duration         : {time.time() - run_start:.1f}s")


if __name__ == "__main__":
    main()
