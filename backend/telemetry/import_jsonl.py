"""One-way import of validated JSONL demo telemetry into the platform sink.

Event IDs and timestamps are preserved, so re-running is idempotent: identical
duplicates are ignored by the sink and conflicting reuse is rejected. The imported
rows must therefore summarize exactly like the source log.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from backend.platform.paths import DEFAULT_DATABASE_PATH, DEFAULT_TELEMETRY_PATH
from backend.stores.repository import StoreRepository
from backend.telemetry.report import load_events
from backend.telemetry.sqlite_store import TelemetryStores
from backend.telemetry.validation import deserialize_event
from contracts.store import StoreScope
from contracts.telemetry import TelemetrySink

DEFAULT_STORE_ID = "pitch-demo"


@dataclass(frozen=True)
class TelemetryImportResult:
    store_id: str
    imported: int
    duplicates_ignored: int


def import_jsonl_events(sink: TelemetrySink, path: Path, *, store_id: str) -> TelemetryImportResult:
    """Replay a JSONL log into a store-scoped sink."""

    imported = duplicates = 0
    for position, snapshot in enumerate(load_events(path), start=1):
        try:
            written = sink.append(deserialize_event(snapshot))
        except ValueError as error:
            raise ValueError(
                f"{path} entry {position} ({snapshot.get('event_type')}): {error}"
            ) from error
        if written:
            imported += 1
        else:
            duplicates += 1
    return TelemetryImportResult(store_id, imported, duplicates)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.telemetry.import_jsonl",
        description="Import a JSONL demo telemetry log into the store-scoped sink.",
    )
    parser.add_argument("--telemetry-path", type=Path, default=DEFAULT_TELEMETRY_PATH)
    parser.add_argument("--store-id", default=DEFAULT_STORE_ID)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        with StoreRepository.open(arguments.database) as stores:
            store = stores.get_store(StoreScope(arguments.store_id))
            with TelemetryStores.open(arguments.database) as telemetry:
                result = import_jsonl_events(
                    telemetry.for_store(store), arguments.telemetry_path, store_id=store.store_id
                )
    except (OSError, ValueError, LookupError) as error:
        raise SystemExit(f"error: {error}") from error
    print(
        f"imported {result.imported} events into {result.store_id}; "
        f"{result.duplicates_ignored} duplicates ignored"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
