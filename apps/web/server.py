"""A dependency-free local web server for the Issue #1 vertical slice."""

from __future__ import annotations

import argparse
import html
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from uuid import UUID, uuid4

from backend.catalog.repository import LoadedCatalog, load_fixture_catalog
from backend.search.placeholder import PlaceholderSearchService
from backend.telemetry.jsonl_store import JsonlTelemetryStore, new_event
from contracts.catalog import CatalogItem
from contracts.search import SearchQuery, SearchService
from contracts.telemetry import EventType

ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parent / "static"


class WebApplication:
    def __init__(self, catalog: LoadedCatalog, telemetry: JsonlTelemetryStore) -> None:
        self.catalog = catalog
        self.telemetry = telemetry
        self.search: SearchService = PlaceholderSearchService(catalog)

    def handler(self) -> type[BaseHTTPRequestHandler]:
        application = self

        class ShopSearchHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
                try:
                    application._handle(self)
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

    def _handle(self, request: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(request.path)
        if parsed.path == "/health":
            self._respond(request, HTTPStatus.OK, "text/plain; charset=utf-8", "ok")
            return
        if parsed.path == "/static/style.css":
            self._respond(
                request,
                HTTPStatus.OK,
                "text/css; charset=utf-8",
                (STATIC_ROOT / "style.css").read_text(),
            )
            return

        session_id, new_session = self._session(request)
        if new_session:
            self.telemetry.append(
                new_event(
                    EventType.SESSION_STARTED,
                    session_id,
                    self.catalog.store.store_id,
                    {"traffic": "fixture_test"},
                )
            )
        if parsed.path == "/":
            self._catalog_page(request, parsed.query, session_id, new_session)
            return
        if parsed.path.startswith("/items/"):
            self._item_page(
                request, parsed.path.removeprefix("/items/"), parsed.query, session_id, new_session
            )
            return
        self._respond(
            request,
            HTTPStatus.NOT_FOUND,
            "text/plain; charset=utf-8",
            "Not found",
            new_session,
            session_id,
        )

    def _catalog_page(
        self, request: BaseHTTPRequestHandler, raw_query: str, session_id: str, new_session: bool
    ) -> None:
        parameters = parse_qs(raw_query)
        query_text = parameters.get("q", [""])[0]
        if len(query_text) > 500:
            raise ValueError("query too long")
        self.telemetry.append(
            new_event(
                EventType.CATALOG_OPENED,
                session_id,
                self.catalog.store.store_id,
                {"traffic": "fixture_test"},
            )
        )
        search_id = None
        result_items = self.catalog.items[:12]
        if query_text.strip():
            response = self.search.search(SearchQuery(text=query_text))
            search_id = response.search_id
            self.telemetry.append(
                new_event(
                    EventType.SEARCH_SUBMITTED,
                    session_id,
                    self.catalog.store.store_id,
                    {
                        "query": query_text,
                        "filters": {},
                        "catalog_version": response.catalog_version,
                        "traffic": "fixture_test",
                    },
                    search_id,
                )
            )
            self.telemetry.append(
                new_event(
                    EventType.SEARCH_RESULTS_RETURNED,
                    session_id,
                    self.catalog.store.store_id,
                    {
                        "query": query_text,
                        "result_count": len(response.results),
                        "results": [
                            {
                                **self.catalog.public_snapshot(
                                    self.catalog.items_by_result(result.item_id)
                                ),
                                "rank": result.rank,
                            }
                            for result in response.results
                        ],
                        "catalog_version": response.catalog_version,
                        "placeholder": True,
                        "traffic": "fixture_test",
                    },
                    search_id,
                )
            )
            result_items = tuple(
                self.catalog.items_by_result(result.item_id) for result in response.results
            )
        body = _catalog_html(self.catalog, result_items, query_text, search_id)
        self._respond(
            request, HTTPStatus.OK, "text/html; charset=utf-8", body, new_session, session_id
        )

    def _item_page(
        self,
        request: BaseHTTPRequestHandler,
        item_id: str,
        raw_query: str,
        session_id: str,
        new_session: bool,
    ) -> None:
        item = self.catalog.get(item_id)
        if item is None:
            self._respond(
                request,
                HTTPStatus.NOT_FOUND,
                "text/plain; charset=utf-8",
                "Fixture item not found",
                new_session,
                session_id,
            )
            return
        search_id = parse_qs(raw_query).get("search_id", [None])[0]
        self.telemetry.append(
            new_event(
                EventType.ITEM_OPENED,
                session_id,
                self.catalog.store.store_id,
                {
                    **self.catalog.public_snapshot(item),
                    "catalog_version": self.catalog.version,
                    "traffic": "fixture_test",
                },
                search_id,
            )
        )
        self._respond(
            request,
            HTTPStatus.OK,
            "text/html; charset=utf-8",
            _item_html(self.catalog, item),
            new_session,
            session_id,
        )

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


def create_server(
    catalog_path: Path, store_path: Path, telemetry_path: Path, port: int = 8000
) -> ThreadingHTTPServer:
    catalog = load_fixture_catalog(catalog_path, store_path)
    application = WebApplication(catalog, JsonlTelemetryStore(telemetry_path))
    return ThreadingHTTPServer(("127.0.0.1", port), application.handler())


def _catalog_html(
    catalog: LoadedCatalog, items: tuple[CatalogItem, ...], query: str, search_id: str | None
) -> str:
    cards = "".join(_card_html(item, search_id, catalog.store.currency) for item in items)
    heading = f"Results for “{html.escape(query)}”" if query else "Fixture catalog preview"
    return _page(
        catalog.store.display_name,
        f"""
        <main>
          <p class="fixture-banner">DEMO / TEST FIXTURE — not Customer Zero inventory and not a real store catalog.</p>
          <h1>{html.escape(catalog.store.display_name)}</h1>
          <p>This page proves the catalog → search → item → telemetry path. Results use deterministic token matching; semantic retrieval is not implemented.</p>
          <form action="/" method="get"><label for="q">Placeholder search</label><input id="q" name="q" value="{html.escape(query)}" placeholder="Try blue or clear"><button type="submit">Search fixture catalog</button></form>
          <h2>{heading}</h2><section class="grid">{cards}</section>
        </main>
        """,
    )


def _card_html(item: CatalogItem, search_id: str | None, currency: str) -> str:
    query = f"?search_id={quote(search_id)}" if search_id else ""
    attributes = ", ".join(f"{key}: {value}" for key, value in item.attributes.items())
    price = f"{item.price} {currency}" if item.price is not None else "Price unknown"
    return f"""<article class="card"><div class="fixture-image">FIXTURE<br>VISUAL</div><p class="eyebrow">Demo/test record</p><h3><a href="/items/{quote(item.item_id)}{query}">{html.escape(item.title or item.item_id)}</a></h3><p>{html.escape(item.category or "")}</p><p>{html.escape(attributes)}</p><strong>{html.escape(price)}</strong></article>"""


def _item_html(catalog: LoadedCatalog, item: CatalogItem) -> str:
    evidence = item.evidence[0]
    return _page(
        item.title or item.item_id,
        f"""
        <main><p class="fixture-banner">DEMO / TEST FIXTURE — not Customer Zero inventory.</p><p><a href="/">← Return to fixture catalog</a></p><div class="fixture-image detail">FIXTURE<br>VISUAL</div><h1>{html.escape(item.title or item.item_id)}</h1><p>{html.escape(item.category or "")}</p><p>Fixture attributes: {html.escape(str(item.attributes))}</p><p>Fixture price: {html.escape(str(item.price))} {html.escape(catalog.store.currency)}</p><p>Fixture provenance only: manual source {html.escape(evidence.source_id)} recorded at {html.escape(evidence.observed_at.isoformat())}.</p><p>This is not a customer-facing availability claim.</p></main>
        """,
    )


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title><link rel="stylesheet" href="/static/style.css"></head><body>{body}</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ShopSearch Issue #1 fixture slice.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--telemetry-path", type=Path, default=ROOT / "data" / "local" / "telemetry.jsonl"
    )
    arguments = parser.parse_args()
    server = create_server(
        ROOT / "data/demo/catalog.json",
        ROOT / "data/demo/store.json",
        arguments.telemetry_path,
        arguments.port,
    )
    print(f"Fixture slice listening at http://127.0.0.1:{arguments.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
