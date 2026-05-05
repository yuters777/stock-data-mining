# Read-only dashboard DB access.
# Uses aiosqlite.connect() directly — tracked in ALLOWED_OFFENDERS pending
# an open_db_ro() helper.  Do NOT migrate until that helper exists.
import aiosqlite


async def get_db_ro(path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA query_only=ON")
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    return db
