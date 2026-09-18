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
