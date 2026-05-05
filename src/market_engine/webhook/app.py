"""
Webhook ASGI application (aiohttp-style).

Exposes:
  POST /webhook/trade   — ingest trade events
  GET  /webhook/health  — liveness probe

DB connections in route handlers use get_db() from market_engine.db.connection.
Wave 5b: migrated 1 raw connect call-site (list-events handler) to get_db().
"""
import json
import logging
from pathlib import Path
from typing import Any

from market_engine.db.connection import get_db
from market_engine.webhook.worker import process_trade_event

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simple request / response shims (no framework dependency)
# ---------------------------------------------------------------------------

class Request:
    def __init__(self, method: str, path: str, body: bytes = b"", app: dict | None = None):
        self.method = method
        self.path = path
        self._body = body
        self.app: dict[str, Any] = app or {}

    async def json(self) -> Any:
        return json.loads(self._body)


class Response:
    def __init__(self, body: Any, status: int = 200):
        self.body = body
        self.status = status


# ---------------------------------------------------------------------------
# Route: POST /webhook/trade
# ---------------------------------------------------------------------------

async def handle_trade_event(request: Request) -> Response:
    try:
        raw = await request.json()
    except (ValueError, KeyError):
        return Response({"error": "bad_request"}, status=400)

    db_path = request.app.get("db_path", "market_engine.db")
    result = await process_trade_event(db_path, raw)
    status = 200 if result.get("status") == "processed" else 422
    return Response(result, status=status)


# ---------------------------------------------------------------------------
# Route: GET /webhook/health
# ---------------------------------------------------------------------------

async def handle_health(request: Request) -> Response:
    return Response({"status": "ok"})


# ---------------------------------------------------------------------------
# Route: GET /webhook/events  — list recent events  (~line 163)
# ---------------------------------------------------------------------------

async def handle_list_events(request: Request) -> Response:
    db_path = request.app.get("db_path", "market_engine.db")
    limit = int(request.app.get("events_limit", 50))
    db = await get_db(db_path)
    try:
        cur = await db.execute(
            "SELECT id, symbol, event_type, received_at FROM trade_events"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        events = [dict(r) for r in rows]
    finally:
        await db.close()
    return Response({"events": events})


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

_ROUTES: dict[tuple[str, str], Any] = {
    ("POST", "/webhook/trade"): handle_trade_event,
    ("GET",  "/webhook/health"): handle_health,
    ("GET",  "/webhook/events"): handle_list_events,
}


async def dispatch(request: Request) -> Response:
    handler = _ROUTES.get((request.method, request.path))
    if handler is None:
        return Response({"error": "not_found"}, status=404)
    return await handler(request)
