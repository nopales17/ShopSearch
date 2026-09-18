"""Production WSGI adapter for the photographic pitch storefront.

ADR-0004 selects a Flask application served by Waitress as the production HTTP
adapter. The adapter reuses the existing P1 composition and handler dispatch so that
S1 changes transport only: routes, view functions, response headers, cookies, telemetry
and stored data keep their existing behavior.
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

from apps.web.pitch_server import PitchApplication, build_pitch_application
from backend.search.multimodal import TextEncoder


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


def create_pitch_app(
    telemetry_path: Path | None = None, encoder: TextEncoder | None = None
) -> Flask:
    """Return the Flask application serving the existing pitch storefront."""

    application = build_pitch_application(telemetry_path, encoder)
    app = Flask(__name__, static_folder=None)
    app.url_map.merge_slashes = False

    @app.route("/", defaults={"path": ""}, methods=["GET"])
    @app.route("/<path:path>", methods=["GET"])
    def dispatch(path: str) -> Response:
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
) -> WaitressServer:
    """Return a bound Waitress server for the pitch application."""

    return WaitressServer(create_pitch_app(telemetry_path, encoder), host=host, port=port)


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
