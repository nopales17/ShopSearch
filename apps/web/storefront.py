"""Storefront composition, application and HTTP response helpers.

S10 separates the generic platform runtime from explicit pitch-demo provisioning.
`open_platform_stack()` opens the configured database and media root, runs the
forward-only migrations and returns the repositories the adapter needs; it never
seeds or imports the demo. `open_demo_stack()` is the explicit developer/demo path
that additionally seeds Form & Field and imports its committed dataset, embeddings
and retrieval-index artifact.

The HTTP helpers here are the small surface the storefront needs from the retired
Issue #1 fixture server: a session cookie, the shared response headers and the
`BaseHTTPRequestHandler` adapter seam used by the legacy S1 server and the WSGI
`_RequestBoundary`. No fixture routing or fixture catalog lives here.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from apps.web import pitch_views as views
from backend.adapters.clip import MODEL_ID, MODEL_REVISION, ClipEncoder
from backend.auth.service import AuthStores
from backend.catalog.pitch_import import import_pitch_dataset
from backend.catalog.read_model import LoadedCatalog
from backend.catalog.store_repository import CatalogRepository
from backend.media.image_store import ImageStore, LocalImageStore, MediaError
from backend.platform.health import RuntimeHealth
from backend.platform.paths import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_DEMO_DATASET_PATH,
    DEFAULT_DEMO_INDEX_PATH,
    DEFAULT_DEMO_STORE_PATH,
    DEFAULT_MEDIA_ROOT,
)
from backend.search.embedding_import import import_pitch_embeddings
from backend.search.multimodal import MultimodalSearchService, TextEncoder
from backend.search.price import parse_price
from backend.search.vector_source import DatabaseVectorSource, VectorCache
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from backend.telemetry.sqlite_store import TelemetryStores
from backend.telemetry.validation import new_event
from contracts.auth import MerchantIdentity
from contracts.search import SearchQuery, SearchService
from contracts.store import Store, StoreScope
from contracts.telemetry import EventType, TelemetrySink, TrafficClass

STATIC_ROOT = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class StorefrontStack:
    """Open, migrated backends one process serves storefront requests through."""

    store_repository: StoreRepository
    catalog_repository: CatalogRepository
    image_store: ImageStore
    telemetry_stores: TelemetryStores
    auth_stores: AuthStores
    # Set only by the explicit demo path: the pitch-demo import/parity artifact.
    index_path: Path | None = None
    # Set only by the explicit demo path: the single store that path serves.
    store: Store | None = None

    @property
    def demo_store(self) -> Store:
        if self.store is None:
            raise RuntimeError("this stack was not opened from the demo provisioning path")
        return self.store

    def close(self) -> None:
        """Release backend connections; safe to call more than once."""

        self.catalog_repository.close()
        self.store_repository.close()
        self.telemetry_stores.close()
        self.auth_stores.close()


def open_platform_stack(
    database_path: Path | None = None, media_root: Path | None = None
) -> StorefrontStack:
    """Open the configured platform backends without provisioning any store.

    S10 requires production startup to be free of demo side effects: this function
    runs the forward-only migrations, opens the repositories and returns. Store
    records, catalogs and merchants must already be provisioned by an operator.
    """

    database = database_path or DEFAULT_DATABASE_PATH
    return StorefrontStack(
        store_repository=StoreRepository.open(database),
        catalog_repository=CatalogRepository.open(database),
        image_store=LocalImageStore(media_root or DEFAULT_MEDIA_ROOT),
        telemetry_stores=TelemetryStores.open(database),
        auth_stores=AuthStores.open(database),
    )


def open_demo_stack(
    database_path: Path | None = None, media_root: Path | None = None
) -> StorefrontStack:
    """Explicitly provision and open the committed Form & Field pitch demo."""

    database = database_path or DEFAULT_DATABASE_PATH
    storefront_media = media_root or DEFAULT_MEDIA_ROOT
    stack = open_platform_stack(database, storefront_media)
    store = seed_store(stack.store_repository, DEFAULT_DEMO_STORE_PATH)
    import_pitch_dataset(
        stack.catalog_repository, stack.image_store, DEFAULT_DEMO_DATASET_PATH, store
    )
    import_pitch_embeddings(
        stack.catalog_repository,
        DEFAULT_DEMO_INDEX_PATH,
        store,
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
    )
    return StorefrontStack(
        store_repository=stack.store_repository,
        catalog_repository=stack.catalog_repository,
        image_store=stack.image_store,
        telemetry_stores=stack.telemetry_stores,
        auth_stores=stack.auth_stores,
        index_path=DEFAULT_DEMO_INDEX_PATH,
        store=store,
    )


class StorefrontApplication:
    """Base HTTP surface shared by the platform storefront and the S1 adapter."""

    def __init__(self, catalog: LoadedCatalog, telemetry: TelemetrySink) -> None:
        self.catalog = catalog
        self.telemetry = telemetry
        self.search: SearchService

    def handler(self) -> type[BaseHTTPRequestHandler]:
        application = self

        class ShopSearchHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
                try:
                    application._handle(self)  # type: ignore[attr-defined]
                except ValueError:
                    application._respond(
                        self,
                        HTTPStatus.BAD_REQUEST,
                        "text/plain; charset=utf-8",
                        "Invalid request or search attribution",
                    )
                except OSError:
                    application._respond(
                        self,
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        "text/plain; charset=utf-8",
                        "Local storage unavailable; please retry",
                    )

            def log_message(self, format: str, *args: object) -> None:
                return

        return ShopSearchHandler

    def _session(self, request: BaseHTTPRequestHandler) -> tuple[str, bool]:
        try:
            cookie = SimpleCookie(request.headers.get("Cookie"))
            if "shopsearch_session" in cookie:
                value = cookie["shopsearch_session"].value
                UUID(value)
                return value, False
        except (CookieError, ValueError):
            pass
        return str(uuid4()), True

    def _respond(
        self,
        request: BaseHTTPRequestHandler,
        status: HTTPStatus,
        content_type: str,
        body: str | bytes,
        new_session: bool = False,
        session_id: str | None = None,
    ) -> None:
        encoded = body.encode("utf-8") if isinstance(body, str) else body
        request.send_response(status)
        request.send_header("Content-Type", content_type)
        request.send_header("Content-Length", str(len(encoded)))
        request.send_header("Cache-Control", "no-store")
        request.send_header("X-Content-Type-Options", "nosniff")
        if new_session and session_id:
            request.send_header(
                "Set-Cookie", f"shopsearch_session={session_id}; Path=/; SameSite=Lax; HttpOnly"
            )
        request.end_headers()
        request.wfile.write(encoded)


class PitchApplication(StorefrontApplication):
    def __init__(
        self,
        catalog: LoadedCatalog,
        telemetry: TelemetrySink,
        search: SearchService,
        store: Store,
        scope: StoreScope,
        catalog_repository: CatalogRepository,
        image_store: ImageStore,
        default_traffic: TrafficClass,
        health: RuntimeHealth,
        *,
        index_path: Path | None = None,
    ) -> None:
        super().__init__(catalog, telemetry)
        self.search = search
        self.store = store
        self.scope = scope
        self.catalog_repository = catalog_repository
        self.image_store = image_store
        self.default_traffic = default_traffic
        self.health = health
        # The committed retrieval index is a pitch-demo import/parity artifact. A
        # platform store's events carry no such hash rather than a fabricated one.
        self.index_sha256 = (
            hashlib.sha256(index_path.read_bytes()).hexdigest() if index_path is not None else None
        )

    def event(
        self,
        kind: EventType,
        session: str,
        payload: dict[str, Any],
        search_id: str | None = None,
        *,
        traffic: TrafficClass,
    ) -> None:
        metadata: dict[str, Any] = {
            "traffic": traffic.value,
            "catalog_version": self.catalog.version,
        }
        if self.index_sha256 is not None:
            metadata["retrieval_index_sha256"] = self.index_sha256
        self.telemetry.append(
            new_event(
                kind,
                session,
                self.scope.store_id,
                {**metadata, **payload},
                search_id,
            )
        )

    def _handle(
        self, request: BaseHTTPRequestHandler, merchant: MerchantIdentity | None = None
    ) -> None:
        # A merchant browsing this store's own storefront is classified separately from
        # customer traffic; anything else keeps the store's default public class.
        traffic = TrafficClass.MERCHANT_SELF if merchant is not None else self.default_traffic
        parsed = urlparse(request.path)
        if parsed.path == "/health":
            healthy, body = self._health_status()
            self._respond(
                request,
                HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE,
                "text/plain",
                body,
            )
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
            self.event(EventType.SESSION_STARTED, session, {}, traffic=traffic)
        status = HTTPStatus.OK
        content_type = "text/html; charset=utf-8"
        if parsed.path == "/":
            self.event(EventType.HOMEPAGE_VIEWED, session, {}, traffic=traffic)
            body = views.home(self.catalog, self.store)
        elif parsed.path == "/credits":
            body = views.credits(self.catalog, self.store)
        elif parsed.path == "/catalog":
            self.event(EventType.CATALOG_OPENED, session, {}, traffic=traffic)
            body = views.catalog_page(self.catalog, self.store, query)
        elif parsed.path == "/api/search":
            category = parameters.get("category", [""])[0]
            if category and category not in {i.category for i in self.catalog.items}:
                raise ValueError("unknown category")
            start = time.perf_counter()
            search_id = None
            coverage = None
            if query.strip():
                response = self.search.search(
                    SearchQuery(text=query, category=category or None, limit=12)
                )
                if response.coverage is None:
                    raise ValueError("search service did not report coverage")
                coverage = response.coverage
                search_id = response.search_id
                filters = parse_price(query).filters()
                if category:
                    filters["category"] = category
                self.event(
                    EventType.SEARCH_SUBMITTED,
                    session,
                    {"query": query, "filters": filters},
                    search_id,
                    traffic=traffic,
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
                        "published_count": coverage.published,
                        "ready_count": coverage.ready,
                        "excluded_unindexed_count": coverage.excluded_unindexed,
                        "results": [
                            {**self.catalog.public_snapshot(item), "rank": rank}
                            for rank, item in enumerate(items, 1)
                        ],
                    },
                    search_id,
                    traffic=traffic,
                )
                if not items:
                    self.event(
                        EventType.ZERO_RESULTS,
                        session,
                        {"query": query, "filters": filters},
                        search_id,
                        traffic=traffic,
                    )
            else:
                items = tuple(
                    i for i in self.catalog.items if not category or i.category == category
                )
            elapsed_ms = (time.perf_counter() - start) * 1000
            body = json.dumps(
                views.result_payload(
                    self.catalog, self.store, items, query, search_id, elapsed_ms, coverage
                )
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
                    EventType.ITEM_OPENED,
                    session,
                    self.catalog.public_snapshot(item),
                    search_id,
                    traffic=traffic,
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
                traffic=traffic,
            )
            content_type, body = "application/json", '{"simulated":true,"contacted_business":false}'
        else:
            status, body = HTTPStatus.NOT_FOUND, "Not found"
        self._respond(request, status, content_type, body, fresh, session)

    def _health_status(self) -> tuple[bool, str]:
        return self.health.check()

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
    vector_cache: VectorCache,
    telemetry: TelemetrySink,
    encoder: TextEncoder | None = None,
    *,
    health: RuntimeHealth,
    index_path: Path | None = None,
    warm_encoder: bool = True,
) -> PitchApplication:
    catalog = catalog_repository.loaded_catalog(store)
    vector_source = DatabaseVectorSource(vector_cache, scope)
    encoder = encoder or ClipEncoder()
    service = MultimodalSearchService(catalog, vector_source, encoder)
    if warm_encoder:
        encoder.text("glass")  # Warm inference at startup, not from the fixed query list.
    default_traffic = TrafficClass.PITCH_DEMO if store.is_demo else TrafficClass.CUSTOMER
    return PitchApplication(
        catalog,
        telemetry,
        service,
        store,
        scope,
        catalog_repository,
        image_store,
        default_traffic,
        health,
        index_path=index_path,
    )
