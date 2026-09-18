"""Production WSGI adapter for the store-scoped photographic storefront.

ADR-0004 selects a Flask application served by Waitress as the production HTTP
adapter. The adapter reuses the existing P1 composition and handler dispatch, so
routes, view functions, response headers, cookies and telemetry keep their behavior.
S2 makes it resolve each request's normalized Host to exactly one store through the
registry; an unregistered host gets a 404 that carries no store data.
"""

from __future__ import annotations

import argparse
import io
import threading
from http import HTTPStatus
from http.client import HTTPMessage
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Mapping

import waitress
from flask import Flask, Response, request

from apps.web.pitch_server import PitchApplication, build_pitch_application, open_demo_stack
from backend.platform.paths import DEFAULT_DEVELOPMENT_HOSTS_PATH
from backend.search.multimodal import TextEncoder
from backend.stores.resolver import HostResolver, load_development_hosts
from contracts.store import StoreScope


def _request_target(environ: Mapping[str, Any]) -> str:
    """Return the raw request target, falling back for WSGI servers without REQUEST_URI."""

    target = environ.get("REQUEST_URI") or environ.get("RAW_URI")
    if target:
        return str(target)
    path_info = str(environ.get("PATH_INFO", ""))
    query_string = str(environ.get("QUERY_STRING", ""))
    return f"{path_info}?{query_string}" if query_string else path_info


def _request_headers(environ: Mapping[str, Any]) -> HTTPMessage:
    headers = HTTPMessage()
    for name, value in environ.items():
        if name.startswith("HTTP_"):
            headers[name[5:].replace("_", "-")] = str(value)
    content_type = environ.get("CONTENT_TYPE")
    if content_type:
        headers["Content-Type"] = str(content_type)
    content_length = environ.get("CONTENT_LENGTH")
    if content_length:
        headers["Content-Length"] = str(content_length)
    return headers


class _RequestBoundary(BaseHTTPRequestHandler):
    """Present one WSGI request through the legacy handler surface.

    The P1 dispatch was written against ``BaseHTTPRequestHandler``. Instances are created
    without a socket; only ``path``, ``headers``, ``wfile`` and the response methods are
    used by that dispatch.
    """

    @classmethod
    def from_environ(cls, environ: Mapping[str, Any]) -> "_RequestBoundary":
        boundary = cls.__new__(cls)
        boundary._load(environ)
        return boundary

    def _load(self, environ: Mapping[str, Any]) -> None:
        self.path = _request_target(environ)
        self.headers = _request_headers(environ)
        self._body = io.BytesIO()
        self.wfile = self._body
        self._status = int(HTTPStatus.OK)
        self._headers: list[tuple[str, str]] = []

    def send_response(self, code: int, message: str | None = None) -> None:
        self._status = int(code)
        self._headers = []
        self._body = io.BytesIO()
        self.wfile = self._body

    def send_header(self, keyword: str, value: str) -> None:
        self._headers.append((keyword, value))

    def end_headers(self) -> None:
        return None

    def log_message(self, format: str, *args: Any) -> None:
        return None

    @property
    def status_code(self) -> int:
        return self._status

    @property
    def response_headers(self) -> list[tuple[str, str]]:
        return self._headers

    @property
    def response_body(self) -> bytes:
        return self._body.getvalue()


def _dispatch(application: PitchApplication, environ: Mapping[str, Any]) -> Response:
    boundary = _RequestBoundary.from_environ(environ)
    try:
        application._handle(boundary)
    except ValueError:
        application._respond(
            boundary,
            HTTPStatus.BAD_REQUEST,
            "text/plain; charset=utf-8",
            "Invalid request or search attribution",
        )
    except OSError:
        application._respond(
            boundary,
            HTTPStatus.SERVICE_UNAVAILABLE,
            "text/plain; charset=utf-8",
            "Local storage unavailable; please retry",
        )
    return Response(
        boundary.response_body,
        status=boundary.status_code,
        headers=boundary.response_headers,
    )


def _plain(status: HTTPStatus, body: str) -> Response:
    """A response for an unresolved host, carrying no store data and no cookie."""

    response = Response(body, status=status, content_type="text/plain; charset=utf-8")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def create_pitch_app(
    telemetry_path: Path | None = None,
    encoder: TextEncoder | None = None,
    database_path: Path | None = None,
    development_hosts_path: Path | None = None,
    media_root: Path | None = None,
    storefronts: Mapping[str, Path] | None = None,
) -> Flask:
    """Return the Flask application serving host-resolved storefronts.

    Every request resolves its normalized `Host` through the store registry to
    exactly one store. An unregistered hostname returns 404 with no store data.
    `config/development_hosts.json` is the explicit local host-to-store map; it
    contains no wildcard, and an unknown host never falls back to a store.

    `storefronts` maps each provisioned store to its vector index; by default only
    the bootstrapped demo store is served. A resolved store that is not provisioned
    gets a 404 rather than another store's catalog.
    """

    stack = open_demo_stack(database_path, media_root)
    development_hosts = load_development_hosts(
        DEFAULT_DEVELOPMENT_HOSTS_PATH if development_hosts_path is None else development_hosts_path
    )
    resolver = HostResolver(stack.store_repository, development_hosts)
    index_paths = (
        {stack.store.store_id: stack.index_path} if storefronts is None else dict(storefronts)
    )
    applications: dict[str, PitchApplication] = {}
    application_lock = threading.Lock()

    def application_for(scope: StoreScope) -> PitchApplication | None:
        index_path = index_paths.get(scope.store_id)
        if index_path is None:
            return None
        with application_lock:
            existing = applications.get(scope.store_id)
            if existing is not None:
                return existing
            store = stack.store_repository.find_store(scope)
            if store is None or not stack.catalog_repository.has_items(scope):
                return None
            application = build_pitch_application(
                store,
                scope,
                stack.catalog_repository,
                stack.image_store,
                index_path,
                telemetry_path,
                encoder,
            )
            applications[scope.store_id] = application
            return application

    app = Flask(__name__, static_folder=None)
    app.url_map.merge_slashes = False

    @app.route("/", defaults={"path": ""}, methods=["GET"])
    @app.route("/<path:path>", methods=["GET"])
    def dispatch(path: str) -> Response:
        scope = resolver.resolve(request.environ.get("HTTP_HOST"))
        if scope is None:
            return _plain(HTTPStatus.NOT_FOUND, "Not found")
        application = application_for(scope)
        if application is None:
            return _plain(HTTPStatus.NOT_FOUND, "Not found")
        return _dispatch(application, request.environ)

    return app


class WaitressServer:
    """Waitress server handle with the lifecycle calls the local server exposed."""

    def __init__(
        self, application: Flask, host: str = "127.0.0.1", port: int = 8000, threads: int = 4
    ) -> None:
        self._server: Any = waitress.create_server(
            application, host=host, port=port, threads=threads
        )
        self._stopping = threading.Event()

    @property
    def server_port(self) -> int:
        return int(self._server.effective_port)

    @property
    def server_address(self) -> tuple[str, int]:
        return (str(self._server.effective_host), self.server_port)

    def serve_forever(self) -> None:
        try:
            self._server.run()
        except OSError:
            # ``close`` can interrupt the async loop with a bad file descriptor; that is
            # expected only for the intentional shutdown path used by the acceptance tests.
            if not self._stopping.is_set():
                raise

    def shutdown(self) -> None:
        self._stopping.set()
        self._server.close()

    def server_close(self) -> None:
        if not self._stopping.is_set():
            self._stopping.set()
            self._server.close()


def create_pitch_server(
    port: int = 8000,
    telemetry_path: Path | None = None,
    encoder: TextEncoder | None = None,
    host: str = "127.0.0.1",
    database_path: Path | None = None,
    development_hosts_path: Path | None = None,
    media_root: Path | None = None,
    storefronts: Mapping[str, Path] | None = None,
) -> WaitressServer:
    """Return a bound Waitress server for the pitch application."""

    return WaitressServer(
        create_pitch_app(
            telemetry_path,
            encoder,
            database_path,
            development_hosts_path,
            media_root,
            storefronts,
        ),
        host=host,
        port=port,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the generic photographic pitch demo on the production WSGI adapter."
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--telemetry-path", type=Path)
    arguments = parser.parse_args()
    server = create_pitch_server(arguments.port, arguments.telemetry_path)
    print(f"Pitch demo ready: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
