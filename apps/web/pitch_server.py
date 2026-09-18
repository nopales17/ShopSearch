"""Legacy standard-library HTTP adapter for the storefront.

S1 served the storefront through this loopback `ThreadingHTTPServer`; ADR-0004 then
selected the Flask/Waitress adapter in `apps/web/wsgi.py` as the production runtime.
S10 keeps this module only as the S1 comparison surface (the adapter parity test) and
as the explicit demo entry point; it no longer carries fixture routing, and it is not
the deployed server.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from apps.web.storefront import (
    StorefrontStack,
    build_pitch_application,
    open_demo_stack,
)
from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.platform.health import RuntimeHealth
from backend.search.multimodal import TextEncoder
from backend.search.vector_source import VectorCache


def runtime_health(stack: StorefrontStack) -> RuntimeHealth:
    """A real database/media health check over an open stack."""

    return RuntimeHealth(
        database_check=stack.catalog_repository.check_health,
        media_check=stack.image_store.check_health,
    )


class StorefrontHttpServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that releases the storefront backends on shutdown."""

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        stack: StorefrontStack,
    ) -> None:
        super().__init__(address, handler)
        self._stack = stack

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            self._stack.close()


def create_pitch_server(
    port: int = 8000,
    encoder: TextEncoder | None = None,
    database_path: Path | None = None,
    media_root: Path | None = None,
) -> ThreadingHTTPServer:
    """Serve the explicitly provisioned pitch demo through the S1 adapter."""

    stack = open_demo_stack(database_path, media_root)
    vector_cache = VectorCache(
        stack.catalog_repository, model_id=MODEL_ID, model_revision=MODEL_REVISION
    )
    application = build_pitch_application(
        stack.demo_store,
        stack.demo_store.scope,
        stack.catalog_repository,
        stack.image_store,
        vector_cache,
        stack.telemetry_stores.for_store(stack.demo_store),
        encoder,
        health=runtime_health(stack),
        index_path=stack.index_path,
    )
    return StorefrontHttpServer(("127.0.0.1", port), application.handler(), stack)


def main() -> None:
    from apps.web.demo import main as demo_main

    demo_main()


if __name__ == "__main__":
    main()
