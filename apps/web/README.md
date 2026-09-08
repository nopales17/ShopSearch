# Web App

Issue #1 uses server-rendered HTML/CSS in a single standard-library Python process.
Run `make run` from the repository root. No JavaScript framework or frontend build
step is needed. `server.py` is a local HTTP/UI adapter, not a public production server.
See ADR-0002 and the root README for runtime, tests and storage constraints.

Do not put domain truth or retrieval logic in UI components.
