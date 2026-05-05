"""Database schema migrations.

NOTE: fmp_press_releases TABLE is intentionally preserved even though the
fetcher category has been disabled (2026-05-05).  mcp/services.py:~line 962
reads this table and gracefully handles the empty case.  Do not drop the table.
"""
import logging

import aiosqlite

from market_engine.db.connection import open_db

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 14


async def _create_tables(db: aiosqlite.Connection) -> None:
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trade_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            event_type  TEXT    NOT NULL,
            payload     TEXT    NOT NULL,
            received_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS trade_validations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    INTEGER NOT NULL REFERENCES trade_events(id),
            status      TEXT    NOT NULL,
            reason      TEXT,
            validated_at TEXT   NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS telegram_dispatches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    INTEGER NOT NULL REFERENCES trade_events(id),
            chat_id     TEXT    NOT NULL,
            message     TEXT    NOT NULL,
            sent_at     TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS fmp_earnings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            eps_actual  REAL,
            eps_est     REAL,
            rev_actual  REAL,
            rev_est     REAL,
            fetched_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS fmp_analyst_estimates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            period      TEXT    NOT NULL,
            eps_avg     REAL,
            rev_avg     REAL,
            fetched_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS fmp_news (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            title       TEXT    NOT NULL,
            url         TEXT,
            published_at TEXT,
            fetched_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS fmp_sec_filings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            form_type   TEXT    NOT NULL,
            filed_at    TEXT,
            url         TEXT,
            fetched_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS fmp_insider_trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            insider     TEXT,
            trade_type  TEXT,
            shares      REAL,
            price       REAL,
            filed_at    TEXT,
            fetched_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        -- Preserved: fetcher disabled 2026-05-05 (FMP 404s), mcp/services.py reads gracefully.
        CREATE TABLE IF NOT EXISTS fmp_press_releases (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            title       TEXT    NOT NULL,
            content     TEXT,
            published_at TEXT,
            fetched_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    await db.commit()


async def run_migrations(db_path: str) -> None:
    async with open_db(db_path) as db:
        await _create_tables(db)
        logger.info("migrations complete, schema_version=%d", _SCHEMA_VERSION)
