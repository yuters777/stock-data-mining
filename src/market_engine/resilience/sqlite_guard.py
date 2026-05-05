"""SQLite resilience guard — retries transient SQLITE_BUSY errors."""
import asyncio
import logging
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 0.1


def sqlite_retry(fn: Callable) -> Callable:
    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                if "database is locked" not in str(exc) or attempt == _MAX_RETRIES:
                    raise
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning("sqlite busy, retry %d/%d in %.2fs", attempt + 1, _MAX_RETRIES, delay)
                await asyncio.sleep(delay)
    return wrapper
