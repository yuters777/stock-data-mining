"""Fetches 8-K filing bodies from SEC EDGAR with local caching."""

import asyncio
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

SEC_USER_AGENT = "stock-data-mining-audit/1.0 (research@market-engine.dev)"
SEC_REQUEST_DELAY = 0.15  # seconds — SEC allows ~10 req/s


async def fetch_filing_body(
    accession: str,
    primary_doc_url: str,
    cache_dir: Path,
    semaphore: asyncio.Semaphore | None = None,
) -> str | None:
    """Fetch (or load from cache) a single 8-K filing body.

    Args:
        accession: EDGAR accession number used as cache filename.
        primary_doc_url: Full URL to the primary document on sec.gov.
        cache_dir: Directory for caching fetched bodies.
        semaphore: Optional semaphore for rate-limiting concurrent fetches.

    Returns:
        HTML body text, or None if fetch failed.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{accession}.html"

    if cache_file.exists():
        logger.debug("Cache hit: %s", accession)
        return cache_file.read_text(encoding="utf-8", errors="replace")

    async def _do_fetch() -> str | None:
        await asyncio.sleep(SEC_REQUEST_DELAY)
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                headers={
                    "User-Agent": SEC_USER_AGENT,
                    "Accept-Encoding": "gzip, deflate",
                },
            ) as client:
                response = await client.get(primary_doc_url)
                response.raise_for_status()
                body = response.text
                cache_file.write_text(body, encoding="utf-8")
                logger.debug("Fetched and cached: %s", accession)
                return body
        except Exception as exc:
            logger.warning("Fetch failed for %s (%s): %s", accession, primary_doc_url, exc)
            return None

    if semaphore is not None:
        async with semaphore:
            return await _do_fetch()
    return await _do_fetch()


async def fetch_all_bodies(
    filings: list[dict],
    cache_dir: Path,
    concurrency: int = 5,
) -> dict[str, str]:
    """Concurrently fetch bodies for a list of filings.

    Args:
        filings: List of dicts each with 'accession_number' and 'primary_doc_url'.
        cache_dir: Cache directory.
        concurrency: Max simultaneous EDGAR requests.

    Returns:
        Dict mapping accession_number -> body text (missing entries = fetch failed).
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _fetch_one(filing: dict) -> tuple[str, str | None]:
        body = await fetch_filing_body(
            filing["accession_number"],
            filing["primary_doc_url"],
            cache_dir,
            semaphore,
        )
        return filing["accession_number"], body

    tasks = [_fetch_one(f) for f in filings]
    results = await asyncio.gather(*tasks)
    return {acc: body for acc, body in results if body is not None}
