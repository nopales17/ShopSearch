"""Production WSGI adapter for the store-scoped photographic storefront.

ADR-0004 selects a Flask application served by Waitress as the production HTTP
adapter. S2 resolves each request's normalized `Host` to exactly one store through the
registry; an unregistered host gets a 404 that carries no store data. S10 makes the
runtime generic: configuration comes from `SHOPSEARCH_*` environment variables and
fails closed, startup never provisions the pitch demo, `/health` checks the real
database and media root before any hostname resolution, and operational logging stays
separate from behavioral telemetry.
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import threading
import time
from http import HTTPStatus
from http.client import HTTPMessage
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import waitress
from flask import Flask, Response, g, request
from werkzeug.exceptions import RequestEntityTooLarge

from apps.web.manage import InteractiveDemo, MerchantShell, ShellResponse, UploadedPhoto
from apps.web.storefront import (
    PitchApplication,
    StorefrontStack,
    build_pitch_application,
    open_platform_stack,
)
from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.auth.service import MERCHANT_COOKIE
from backend.catalog.publish import MerchantPublisher
from backend.media.uploads import MAX_UPLOAD_BYTES
from backend.platform import operational_log
from backend.platform.health import RuntimeHealth
from backend.platform.paths import DEFAULT_DEVELOPMENT_HOSTS_PATH
from backend.runtime.config import RuntimeConfig
from backend.search.indexer import IndexRunReport
from backend.search.multimodal import TextEncoder
from backend.search.vector_source import VectorCache
from backend.stores.resolver import HostResolver, load_development_hosts
from contracts.auth import MerchantIdentity
from contracts.store import Store, StoreScope


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

    The storefront dispatch was written against ``BaseHTTPRequestHandler``. Instances
    are created without a socket; only ``path``, ``headers``, ``wfile`` and the
    response methods are used by that dispatch.
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


def _dispatch(
    application: PitchApplication,
    environ: Mapping[str, Any],
    *,
    merchant: MerchantIdentity | None = None,
) -> Response:
    boundary = _RequestBoundary.from_environ(environ)
    try:
        application._handle(boundary, merchant=merchant)
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


def _uploaded_photos() -> dict[str, UploadedPhoto]:
    """Read bounded upload parts; the request cap already bounds the body."""

    photos: dict[str, UploadedPhoto] = {}
    for field in ("photo",):
        storage = request.files.get(field)
        if storage is None:
            continue
        try:
            data = storage.stream.read(MAX_UPLOAD_BYTES + 1)
        finally:
            # Release the parser's spooled temporary file as soon as it is read.
            storage.close()
        photos[field] = UploadedPhoto(
            filename=storage.filename or "",
            content_type=storage.content_type or "",
            data=data,
        )
    return photos


def _plain(status: HTTPStatus, body: str) -> Response:
    """A response for an unresolved host or a probe, carrying no store data."""

    response = Response(body, status=status, content_type="text/plain; charset=utf-8")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _health_response(status: HTTPStatus, body: str) -> Response:
    """Generic health body; never a path, SQL error, store datum or secret."""

    response = Response(body, status=status, content_type="text/plain")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _shell_response(result: ShellResponse) -> Response:
    """Render a merchant-shell response; never cache authenticated pages."""

    response = Response(result.body, status=result.status, content_type=result.content_type)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if result.location is not None:
        response.headers["Location"] = result.location
    for cookie in result.cookies:
        response.headers.add("Set-Cookie", cookie)
    for name, value in result.headers:
        response.headers.add(name, value)
    return response


def build_runtime_health(stack: StorefrontStack, logger: Any) -> RuntimeHealth:
    """The one health check the WSGI entry point and the S1 adapter share."""

    return RuntimeHealth(
        database_check=stack.catalog_repository.check_health,
        media_check=stack.image_store.check_health,
        logger=logger,
    )


def create_pitch_app(
    encoder: TextEncoder | None = None,
    database_path: Path | None = None,
    development_hosts_path: Path | None = None,
    media_root: Path | None = None,
    storefronts: Iterable[str] | None = None,
    *,
    stack: StorefrontStack | None = None,
    logger: Any | None = None,
    interactive_demo: InteractiveDemo | None = None,
    index_store: Callable[[StoreScope], IndexRunReport] | None = None,
) -> Flask:
    """Return the Flask application serving host-resolved storefronts.

    Every request resolves its normalized `Host` through the store registry to
    exactly one store. An unregistered hostname returns 404 with no store data.

    `storefronts` names the explicitly provisioned stores this composition serves.
    This function opens the configured backends through `open_platform_stack` and
    never seeds a store: callers that want the pitch demo pass an explicitly opened
    demo stack (`apps.web.storefront.open_demo_stack`).

    `interactive_demo` is the explicit in-memory Form & Field demo capability. Only
    `apps.web.demo` passes it, and it is the sole way any storefront composition can
    enable merchant mutation of demo items. Everything else, including production
    `serve()`, leaves it unset and therefore keeps demo stores read-only.
    """

    stack = stack or open_platform_stack(database_path, media_root)
    development_hosts = load_development_hosts(
        DEFAULT_DEVELOPMENT_HOSTS_PATH if development_hosts_path is None else development_hosts_path
    )
    # Default to the bare operational logger: production configures a handler in
    # `serve()`/`apps.web.demo`, while tests and library callers stay quiet unless
    # they attach their own handler.
    logger = logger or logging.getLogger(operational_log.LOGGER_NAME)
    resolver = HostResolver(stack.store_repository, development_hosts)
    provisioned = set() if storefronts is None else set(storefronts)
    vector_cache = VectorCache(
        stack.catalog_repository, model_id=MODEL_ID, model_revision=MODEL_REVISION
    )
    applications: dict[str, tuple[int, PitchApplication]] = {}
    shells: dict[str, MerchantShell] = {}
    application_lock = threading.Lock()
    health = build_runtime_health(stack, logger)

    def shell_for(store: Store) -> MerchantShell:
        with application_lock:
            existing = shells.get(store.store_id)
            if existing is not None:
                return existing
            publisher = MerchantPublisher(
                store,
                stack.catalog_repository,
                stack.image_store,
                interactive_demo=interactive_demo is not None,
            )
            shell = MerchantShell(
                store,
                stack.auth_stores.for_store(store),
                stack.catalog_repository,
                publisher,
                model_id=MODEL_ID,
                model_revision=MODEL_REVISION,
                interactive_demo=interactive_demo,
                index_store=index_store,
            )
            shells[store.store_id] = shell
            return shell

    def application_for(scope: StoreScope) -> PitchApplication | None:
        if scope.store_id not in provisioned:
            return None
        generation = stack.catalog_repository.generations(scope).catalog
        with application_lock:
            existing = applications.get(scope.store_id)
            if existing is not None and existing[0] == generation:
                return existing[1]
            store = stack.store_repository.find_store(scope)
            if store is None or not stack.catalog_repository.has_items(scope):
                return None
            application = build_pitch_application(
                store,
                scope,
                stack.catalog_repository,
                stack.image_store,
                vector_cache,
                stack.telemetry_stores.for_store(store),
                encoder,
                health=RuntimeHealth(
                    database_check=stack.catalog_repository.check_health,
                    media_check=stack.image_store.check_health,
                    logger=logger,
                ),
                index_path=stack.index_path if store.is_demo else None,
            )
            applications[scope.store_id] = (generation, application)
            return application

    app = Flask(__name__, static_folder=None)
    app.url_map.merge_slashes = False

    # S7 replaces the S6 16 KB form cap with a bounded image upload: a 12 MiB image
    # plus multipart framing. Larger bodies are rejected before parsing.
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 64 * 1024

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(error: RequestEntityTooLarge) -> Response:
        return _plain(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "That upload is too large.")

    @app.before_request
    def _start_request_timer() -> None:
        g.shopsearch_started = time.perf_counter()
        g.shopsearch_store_id = ""

    @app.after_request
    def _log_request(response: Response) -> Response:
        # Operational facts only: no query string, body, cookie or CSRF value.
        started = getattr(g, "shopsearch_started", None)
        duration_ms = round((time.perf_counter() - started) * 1000, 2) if started else 0.0
        operational_log.log_event(
            logger,
            "request",
            method=request.method,
            path=request.path,
            status=response.status_code,
            duration_ms=duration_ms,
            store_id=getattr(g, "shopsearch_store_id", "") or None,
        )
        return response

    @app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
    @app.route("/<path:path>", methods=["GET", "POST"])
    def dispatch(path: str) -> Response:
        # Health is answered before hostname resolution so a database or media
        # failure is reported even when no store resolves.
        if request.path == "/health":
            healthy, body = health.check()
            return _health_response(
                HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE, body
            )
        scope = resolver.resolve(request.environ.get("HTTP_HOST"))
        if scope is None:
            return _plain(HTTPStatus.NOT_FOUND, "Not found")
        g.shopsearch_store_id = scope.store_id
        if scope.store_id not in provisioned:
            return _plain(HTTPStatus.NOT_FOUND, "Not found")
        store = stack.store_repository.find_store(scope)
        if store is None:
            return _plain(HTTPStatus.NOT_FOUND, "Not found")
        auth = stack.auth_stores.for_store(store)
        raw_cookie = request.cookies.get(MERCHANT_COOKIE)
        session = auth.identify(raw_cookie) if raw_cookie else None
        if shell_for(store).handles(request.path):
            return _shell_response(
                shell_for(store).handle(
                    method=request.method,
                    path=request.path,
                    cookies=request.cookies,
                    form=request.form,
                    query=request.args,
                    files=_uploaded_photos(),
                )
            )
        application = application_for(scope)
        if application is None:
            return _plain(HTTPStatus.NOT_FOUND, "Not found")
        return _dispatch(
            application, request.environ, merchant=None if session is None else session.identity
        )

    app.extensions["shopsearch_stack"] = stack
    app.extensions["shopsearch_logger"] = logger
    return app


class WaitressServer:
    """Waitress server handle with the lifecycle calls the local server exposed."""

    def __init__(
        self,
        application: Flask,
        host: str = "127.0.0.1",
        port: int = 8000,
        threads: int = 4,
        config: RuntimeConfig | None = None,
    ) -> None:
        self._server: Any = waitress.create_server(
            application, host=host, port=port, threads=threads
        )
        self._stack = application.extensions.get("shopsearch_stack")
        self._logger = application.extensions.get("shopsearch_logger")
        self._config = config
        self._stopping = threading.Event()

    @property
    def server_port(self) -> int:
        return int(self._server.effective_port)

    @property
    def server_address(self) -> tuple[str, int]:
        return (str(self._server.effective_host), self.server_port)

    def serve_forever(self) -> None:
        if self._logger is not None:
            operational_log.log_event(
                self._logger,
                "startup",
                **({"configuration": self._config.describe()} if self._config else {}),
            )
        try:
            self._server.run()
        except OSError:
            # ``close`` can interrupt the async loop with a bad file descriptor; that is
            # expected only for the intentional shutdown path used by the acceptance tests.
            if not self._stopping.is_set():
                raise
        finally:
            if self._logger is not None:
                operational_log.log_event(self._logger, "shutdown")

    def shutdown(self) -> None:
        self._stopping.set()
        self._server.close()

    def server_close(self) -> None:
        if not self._stopping.is_set():
            self._stopping.set()
            self._server.close()
        if self._stack is not None:
            self._stack.close()


def create_pitch_server(
    port: int = 8000,
    encoder: TextEncoder | None = None,
    host: str = "127.0.0.1",
    database_path: Path | None = None,
    development_hosts_path: Path | None = None,
    media_root: Path | None = None,
    storefronts: Iterable[str] | None = None,
    *,
    stack: StorefrontStack | None = None,
    config: RuntimeConfig | None = None,
) -> WaitressServer:
    """Return a bound Waitress server for the storefront composition."""

    return WaitressServer(
        create_pitch_app(
            encoder,
            database_path,
            development_hosts_path,
            media_root,
            storefronts,
            stack=stack,
        ),
        host=host,
        port=port,
        config=config,
    )


def serve(config: RuntimeConfig) -> None:
    """Start the production process from validated configuration."""

    logger = operational_log.configure_operational_logging(config.log_level)
    stack = open_platform_stack(config.database_path, config.media_root)
    server = WaitressServer(
        create_pitch_app(
            stack=stack,
            development_hosts_path=config.development_hosts_path,
            storefronts=config.store_ids,
            logger=logger,
        ),
        host=config.bind_host,
        port=config.port,
        config=config,
    )
    operational_log.log_event(logger, "configuration", configuration=config.describe())
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run ShopSearch from SHOPSEARCH_* environment configuration. "
            "Missing or invalid configuration fails startup; no demo store is created."
        )
    )
    parser.parse_args()
    try:
        config = RuntimeConfig.from_environment()
    except ValueError as error:
        print(f"configuration error: {error}", file=sys.stderr, flush=True)
        raise SystemExit(2) from error
    serve(config)


if __name__ == "__main__":
    main()
