"""Storefront composition over the store-scoped catalog, media and telemetry boundaries.

Routes, view functions, response headers, cookies and telemetry behavior are
unchanged from P1. S3 replaces the runtime JSON catalog with `CatalogRepository`
and serves EXIF-free derivatives through the `ImageStore`; search consumes the
read model plus the committed index through a vector source keyed by item ID.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from apps.web import pitch_views as views
from apps.web.server import ROOT, STATIC_ROOT, WebApplication
from backend.adapters.clip import MODEL_ID, MODEL_REVISION, ClipEncoder
from backend.catalog.pitch_import import import_pitch_dataset
from backend.catalog.read_model import LoadedCatalog
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import ImageStore, LocalImageStore, MediaError
from backend.platform.paths import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_DEMO_DATASET_PATH,
    DEFAULT_DEMO_INDEX_PATH,
    DEFAULT_DEMO_STORE_PATH,
    DEFAULT_MEDIA_ROOT,
)
from backend.search.multimodal import MultimodalSearchService, TextEncoder
from backend.search.price import parse_price
from backend.search.vector_source import CommittedIndexVectorSource
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from backend.telemetry.jsonl_store import JsonlTelemetryStore, new_event
from contracts.search import SearchQuery, SearchService
from contracts.store import Store, StoreScope
from contracts.telemetry import EventType

# The demo store keeps its P1 telemetry classification (ADR-0005 §8).
DEMO_TRAFFIC = "pitch_demo"


@dataclass(frozen=True)
class StorefrontStack:
    """Open, migrated backends the storefront adapter reads through."""

    store_repository: StoreRepository
    catalog_repository: CatalogRepository
    image_store: ImageStore
    store: Store
    index_path: Path


def open_demo_stack(
    database_path: Path | None = None, media_root: Path | None = None
) -> StorefrontStack:
    """Open the platform backends and idempotently provision the demo store."""

    store_repository = StoreRepository.open(database_path or DEFAULT_DATABASE_PATH)
    catalog_repository = CatalogRepository.open(database_path or DEFAULT_DATABASE_PATH)
    image_store = LocalImageStore(media_root or DEFAULT_MEDIA_ROOT)
    store = seed_store(store_repository, DEFAULT_DEMO_STORE_PATH)
    import_pitch_dataset(catalog_repository, image_store, DEFAULT_DEMO_DATASET_PATH, store)
    return StorefrontStack(
        store_repository, catalog_repository, image_store, store, DEFAULT_DEMO_INDEX_PATH
    )


class PitchApplication(WebApplication):
    def __init__(
        self,
        catalog: LoadedCatalog,
        telemetry: JsonlTelemetryStore,
        search: SearchService,
        store: Store,
        scope: StoreScope,
        catalog_repository: CatalogRepository,
        image_store: ImageStore,
        index_path: Path,
    ) -> None:
        super().__init__(catalog, telemetry)
        self.search = search
        self.store = store
        self.scope = scope
        self.catalog_repository = catalog_repository
        self.image_store = image_store
        self.index_sha256 = hashlib.sha256(index_path.read_bytes()).hexdigest()

    def event(
        self, kind: EventType, session: str, payload: dict[str, Any], search_id: str | None = None
    ) -> None:
        self.telemetry.append(
            new_event(
                kind,
                session,
                self.scope.store_id,
                {
                    "traffic": DEMO_TRAFFIC,
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
        static_assets = {
            "/static/pitch.css": (STATIC_ROOT / "pitch.css", "text/css"),
            "/static/pitch.js": (STATIC_ROOT / "pitch.js", "text/javascript"),
        }
        if parsed.path in static_assets:
            path, mime = static_assets[parsed.path]
            self._respond(request, HTTPStatus.OK, mime, path.read_bytes())
            return
        media = self._media(parsed.path)
        if media is not None:
            data, mime = media
            self._respond(request, HTTPStatus.OK, mime, data)
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
            self.event(EventType.HOMEPAGE_VIEWED, session, {})
            body = views.home(self.catalog, self.store)
        elif parsed.path == "/credits":
            body = views.credits(self.catalog, self.store)
        elif parsed.path == "/catalog":
            self.event(EventType.CATALOG_OPENED, session, {})
            body = views.catalog_page(self.catalog, self.store, query)
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
                views.result_payload(self.catalog, self.store, items, query, search_id, elapsed_ms)
            )
            content_type = "application/json"
        elif parsed.path.startswith("/items/"):
            item = self.catalog.get(parsed.path.removeprefix("/items/"))
            if item is None:
                status, body = (
                    HTTPStatus.NOT_FOUND,
                    views.page(
                        self.store,
                        "Not found",
                        '<main class="credits"><h1>Object not found.</h1><a href="/catalog">Explore the collection →</a></main>',
                    ),
                )
            else:
                search_id = parameters.get("search_id", [None])[0]
                self.event(
                    EventType.ITEM_OPENED, session, self.catalog.public_snapshot(item), search_id
                )
                body = views.item_page(item, self.store, query, search_id)
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

    def _media(self, path: str) -> tuple[bytes, str] | None:
        """Serve an EXIF-free stored derivative for the resolved store, or nothing."""

        if path.startswith("/images/") and path.endswith(".jpg"):
            item_id = path[len("/images/") : -len(".jpg")]
            if not item_id or "/" in item_id:
                return None
            image = self.catalog_repository.display_image(self.scope, item_id)
        elif path.startswith("/media/"):
            parts = path.split("/")
            if len(parts) != 5 or parts[2] != self.scope.store_id:
                return None
            try:
                image = self.catalog_repository.image_by_address(self.scope, parts[3], parts[4])
            except MediaError:
                return None
        else:
            return None
        if image is None:
            return None
        try:
            return self.image_store.read(self.scope, image.sha256, image.variant), image.media_type
        except OSError:
            return None


def build_pitch_application(
    store: Store,
    scope: StoreScope,
    catalog_repository: CatalogRepository,
    image_store: ImageStore,
    index_path: Path,
    telemetry_path: Path | None = None,
    encoder: TextEncoder | None = None,
) -> PitchApplication:
    catalog = catalog_repository.loaded_catalog(store)
    vector_source = CommittedIndexVectorSource(
        index_path,
        expected_catalog_version=catalog.version,
        expected_model_id=MODEL_ID,
        expected_model_revision=MODEL_REVISION,
    )
    encoder = encoder or ClipEncoder()
    service = MultimodalSearchService(catalog, vector_source, encoder)
    encoder.text("glass")  # Warm inference at startup, not from the fixed query list.
    telemetry = JsonlTelemetryStore(
        telemetry_path or ROOT / "data/local/pitch-telemetry.jsonl", traffic=DEMO_TRAFFIC
    )
    return PitchApplication(
        catalog, telemetry, service, store, scope, catalog_repository, image_store, index_path
    )


def create_pitch_server(
    port: int = 8000,
    telemetry_path: Path | None = None,
    encoder: TextEncoder | None = None,
    database_path: Path | None = None,
    media_root: Path | None = None,
) -> ThreadingHTTPServer:
    stack = open_demo_stack(database_path, media_root)
    application = build_pitch_application(
        stack.store,
        stack.store.scope,
        stack.catalog_repository,
        stack.image_store,
        stack.index_path,
        telemetry_path,
        encoder,
    )
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
