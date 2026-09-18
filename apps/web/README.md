# Web App

Issue #1 uses server-rendered HTML/CSS in a single standard-library Python process.
Run `make run` from the repository root. No JavaScript framework or frontend build
step is needed. `server.py` is a local HTTP/UI adapter, not a public production server.
See ADR-0002 and the root README for runtime, tests and storage constraints.

The photographic storefront is served by `wsgi.py`, the Flask application and Waitress
entry point selected in ADR-0004. `pitch_server.py` retains the P1 composition and the
superseded standard-library entry point.

Do not put domain truth or retrieval logic in UI components.
