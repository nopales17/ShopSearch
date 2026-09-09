"""P1 web composition on the Issue #1 HTTP/catalog/search/telemetry boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from apps.web import pitch_views as views
from apps.web.server import ROOT, STATIC_ROOT, WebApplication
from backend.adapters.clip import ClipEncoder
from backend.catalog.pitch import load_pitch_catalog
from backend.catalog.repository import LoadedCatalog
from backend.search.multimodal import MultimodalSearchService, TextEncoder
from backend.search.price import parse_price
from backend.telemetry.jsonl_store import JsonlTelemetryStore, new_event
from contracts.search import SearchQuery, SearchService
from contracts.telemetry import EventType


class PitchApplication(WebApplication):
    def __init__(
        self, catalog: LoadedCatalog, telemetry: JsonlTelemetryStore, search: SearchService
    ) -> None:
        super().__init__(catalog, telemetry)
        self.search = search
        self.index_sha256 = hashlib.sha256(
            (ROOT / "data/pitch/image_index.json").read_bytes()
        ).hexdigest()

    def event(
        self, kind: EventType, session: str, payload: dict[str, Any], search_id: str | None = None
    ) -> None:
        self.telemetry.append(
            new_event(
                kind,
                session,
                self.catalog.store.store_id,
                {
                    "traffic": "pitch_demo",
                    "catalog_version": self.catalog.version,
                    "retrieval_index_sha256": self.index_sha256,
                    **payload,
                },
                search_id,
            )
        )

    def _handle(self, request: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(request.path)
        if parsed.path == "/health":
            self._respond(request, HTTPStatus.OK, "text/plain", "ok")
            return
        assets = {
            "/static/pitch.css": (STATIC_ROOT / "pitch.css", "text/css"),
            "/static/pitch.js": (STATIC_ROOT / "pitch.js", "text/javascript"),
        }
        for asset_item in self.catalog.items:
            assets[asset_item.image_uri or ""] = (
                ROOT / "data/pitch/images" / f"{asset_item.item_id}.jpg",
                "image/jpeg",
            )
        if parsed.path in assets:
            path, mime = assets[parsed.path]
            self._respond(request, HTTPStatus.OK, mime, path.read_bytes())
            return
        parameters = parse_qs(parsed.query)
        query = parameters.get("q", [""])[0]
        if len(query) > 500:
            raise ValueError("query too long")
        session, fresh = self._session(request)
        if fresh:
            self.event(EventType.SESSION_STARTED, session, {})
        status = HTTPStatus.OK
        content_type = "text/html; charset=utf-8"
        if parsed.path == "/":
            body = views.home(self.catalog)
        elif parsed.path == "/credits":
            body = views.credits(self.catalog)
        elif parsed.path == "/catalog":
            self.event(EventType.CATALOG_OPENED, session, {})
            body = views.catalog_page(self.catalog, query)
        elif parsed.path == "/api/search":
            category = parameters.get("category", [""])[0]
            if category and category not in {i.category for i in self.catalog.items}:
                raise ValueError("unknown category")
            start = time.perf_counter()
            search_id = None
            if query.strip():
                response = self.search.search(
                    SearchQuery(text=query, category=category or None, limit=12)
                )
                search_id = response.search_id
                filters = parse_price(query).filters()
                if category:
                    filters["category"] = category
                self.event(
                    EventType.SEARCH_SUBMITTED,
                    session,
                    {"query": query, "filters": filters},
                    search_id,
                )
                items = tuple(self.catalog.items_by_result(r.item_id) for r in response.results)
                self.event(
                    EventType.SEARCH_RESULTS_RETURNED,
                    session,
                    {
                        "query": query,
                        "filters": filters,
                        "placeholder": False,
                        "result_count": len(items),
                        "results": [
                            {**self.catalog.public_snapshot(item), "rank": rank}
                            for rank, item in enumerate(items, 1)
                        ],
                    },
                    search_id,
                )
                if not items:
                    self.event(
                        EventType.ZERO_RESULTS,
                        session,
                        {"query": query, "filters": filters},
                        search_id,
                    )
            else:
                items = tuple(
                    i for i in self.catalog.items if not category or i.category == category
                )
            elapsed_ms = (time.perf_counter() - start) * 1000
            body = json.dumps(
                views.result_payload(self.catalog, items, query, search_id, elapsed_ms)
            )
            content_type = "application/json"
        elif parsed.path.startswith("/items/"):
            item = self.catalog.get(parsed.path.removeprefix("/items/"))
            if item is None:
                status, body = (
                    HTTPStatus.NOT_FOUND,
                    views.page(
                        "Not found",
                        '<main class="credits"><h1>Object not found.</h1><a href="/catalog">Explore the collection →</a></main>',
                    ),
                )
            else:
                search_id = parameters.get("search_id", [None])[0]
                self.event(
                    EventType.ITEM_OPENED, session, self.catalog.public_snapshot(item), search_id
                )
                body = views.item_page(item, query, search_id)
        elif parsed.path == "/api/demo-action":
            item = self.catalog.get(parameters.get("item_id", [""])[0])
            kind = parameters.get("kind", [""])[0]
            if item is None or kind not in ("call", "directions"):
                raise ValueError("invalid demo action")
            search_id = parameters.get("search_id", [None])[0]
            event_type = EventType.CALL_CLICKED if kind == "call" else EventType.DIRECTIONS_CLICKED
            self.event(
                event_type,
                session,
                {**self.catalog.public_snapshot(item), "simulated": True},
                search_id,
            )
            content_type, body = "application/json", '{"simulated":true,"contacted_business":false}'
        else:
            status, body = HTTPStatus.NOT_FOUND, "Not found"
        self._respond(request, status, content_type, body, fresh, session)


def create_pitch_server(
    port: int = 8000, telemetry_path: Path | None = None, encoder: TextEncoder | None = None
) -> ThreadingHTTPServer:
    catalog = load_pitch_catalog(ROOT / "data/pitch/catalog.json")
    encoder = encoder or ClipEncoder()
    service = MultimodalSearchService(catalog, ROOT / "data/pitch/image_index.json", encoder)
    encoder.text("glass")  # Warm inference at startup, not from the fixed query list.
    telemetry = JsonlTelemetryStore(
        telemetry_path or ROOT / "data/local/pitch-telemetry.jsonl", traffic="pitch_demo"
    )
    application = PitchApplication(catalog, telemetry, service)
    return ThreadingHTTPServer(("127.0.0.1", port), application.handler())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the generic photographic pitch demo locally.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--telemetry-path", type=Path)
    args = parser.parse_args()
    server = create_pitch_server(args.port, args.telemetry_path)
    print(f"Pitch demo ready: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
