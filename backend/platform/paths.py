"""Repository paths for the initial deployment implementations."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = REPOSITORY_ROOT / "data" / "local" / "shopsearch.sqlite3"
DEFAULT_MEDIA_ROOT = REPOSITORY_ROOT / "data" / "local" / "media"
DEFAULT_DEVELOPMENT_HOSTS_PATH = REPOSITORY_ROOT / "config" / "development_hosts.json"
DEFAULT_DEMO_STORE_PATH = REPOSITORY_ROOT / "data" / "stores" / "pitch-demo.json"
DEFAULT_DEMO_DATASET_PATH = REPOSITORY_ROOT / "data" / "pitch" / "catalog.json"
DEFAULT_DEMO_INDEX_PATH = REPOSITORY_ROOT / "data" / "pitch" / "image_index.json"
DEFAULT_TELEMETRY_PATH = REPOSITORY_ROOT / "data" / "local" / "pitch-telemetry.jsonl"

# S11: the interactive Form & Field demo is disposable local state. It gets its own
# ignored runtime root so a demo upload or reset can never touch the generic local
# platform database, another store or a configured production path.
DEFAULT_DEMO_RUNTIME_ROOT = REPOSITORY_ROOT / "data" / "local" / "form-and-field-demo"


def demo_runtime_paths(root: Path | None = None) -> tuple[Path, Path]:
    """Return the dedicated demo runtime's ``(database_path, media_root)``."""

    base = DEFAULT_DEMO_RUNTIME_ROOT if root is None else root
    return base / "shopsearch.sqlite3", base / "media"
