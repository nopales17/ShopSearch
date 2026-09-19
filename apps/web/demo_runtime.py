"""The dedicated, disposable Form & Field demo runtime (S11).

The interactive demo needs merchant mutations (uploads, edits, listing changes) that
must never be confused with the committed museum corpus or with production state. It
therefore runs from its own ignored runtime root, and recreating that root is the
whole reset story: no row-by-row deletion, no shared production-style database and no
reach into any other store or path.

`bootstrap_demo_runtime()` is idempotent and additive: it creates the runtime when it
is missing, seeds Form & Field, imports the committed catalog and embeddings, ensures
the local demonstration credential, and leaves an existing runtime's uploads intact.
`reset_demo_runtime()` refuses to touch a runtime a live demo process is using, deletes
only that exact root, rebuilds the pristine baseline and verifies it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from apps.web.storefront import StorefrontStack, open_demo_stack
from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.auth.service import MerchantAuth
from backend.catalog.pitch import load_pitch_catalog
from backend.platform.paths import (
    DEFAULT_DEMO_DATASET_PATH,
    DEFAULT_DEMO_RUNTIME_ROOT,
    demo_runtime_paths,
)
from backend.search.vector_source import EMBEDDING_DIMENSIONS

# The local demonstration credential. It exists only in this explicit demo layer: it is
# never a backend/auth default, a store field, an environment setting or a deployment
# value, and generic production startup never provisions or reveals it.
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo"

DEMO_RUNTIME_DIRNAME = "form-and-field-demo"
DEMO_PID_FILENAME = "demo.pid"


class DemoRuntimeError(RuntimeError):
    """Raised when the dedicated demo runtime cannot be opened, reset or verified."""


@dataclass(frozen=True)
class DemoRuntimeReport:
    """What the dedicated demo runtime contains right now."""

    root: Path
    database_path: Path
    media_root: Path
    store_id: str
    items: int
    ready_embeddings: int
    uploaded_items: int
    baseline_items: int
    credential_ok: bool

    @property
    def is_pristine_baseline(self) -> bool:
        """True only for the committed catalog with no local demo mutation at all."""

        return (
            self.items == self.baseline_items
            and self.ready_embeddings == self.baseline_items
            and self.uploaded_items == 0
        )

    def describe(self, headline: str) -> str:
        return (
            f"{headline}: {self.items} items, {self.ready_embeddings} ready embeddings, "
            f"{self.uploaded_items} local uploads; credential "
            f"{DEMO_USERNAME}/{DEMO_PASSWORD} "
            f"{'verified' if self.credential_ok else 'NOT verified'}\n"
            f"runtime root: {self.root}"
        )


def demo_runtime_root(root: Path | None = None) -> Path:
    """The validated dedicated demo runtime root, or an error.

    The name check is the guard that makes recursive removal safe: this module only
    ever operates on a directory called ``form-and-field-demo``, never on the
    repository, a home directory, a configured production path or a sibling store.
    """

    base = (DEFAULT_DEMO_RUNTIME_ROOT if root is None else root).expanduser()
    resolved = base.resolve()
    if resolved.name != DEMO_RUNTIME_DIRNAME:
        raise DemoRuntimeError(
            f"refusing to operate on {resolved}: the dedicated demo runtime directory "
            f"must be named {DEMO_RUNTIME_DIRNAME!r}"
        )
    return resolved


def ensure_demo_credential(
    auth: MerchantAuth, *, username: str = DEMO_USERNAME, password: str = DEMO_PASSWORD
) -> None:
    """Provision the local demonstration credential through the unchanged S6 machinery."""

    existing = {identity.username for identity in auth.list_merchants()}
    if username in existing:
        # The explicit reset path revokes any session issued by an earlier run.
        auth.reset_password(username, password)
    else:
        auth.create_merchant(username, password)


def record_demo_process(root: Path | None, pid: int) -> Path:
    """Remember which process owns this runtime, so a reset can refuse to race it."""

    base = demo_runtime_root(root)
    pid_path = base / DEMO_PID_FILENAME
    pid_path.write_text(f"{pid}\n", encoding="utf-8")
    return pid_path


def clear_demo_process(root: Path | None) -> None:
    try:
        (demo_runtime_root(root) / DEMO_PID_FILENAME).unlink()
    except OSError:
        return


def demo_runtime_in_use(root: Path | None = None) -> int | None:
    """The pid of a live demo process using this runtime, or None when it is stopped."""

    pid_path = demo_runtime_root(root) / DEMO_PID_FILENAME
    try:
        raw = pid_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    pid = int(raw)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None  # A stale pid file from a crashed or killed demo is not "in use".
    except PermissionError:
        return pid
    return pid


def bootstrap_demo_runtime(
    root: Path | None = None,
) -> tuple[StorefrontStack, DemoRuntimeReport]:
    """Open the dedicated demo runtime, creating or completing it as needed.

    An existing runtime keeps its uploads and mutations: seeding, the catalog import and
    the embedding import are all idempotent additions, and nothing here resets the
    catalog. The known local credential is re-established every start.
    """

    base = demo_runtime_root(root)
    database_path, media_root = demo_runtime_paths(base)
    base.mkdir(parents=True, exist_ok=True)
    stack = open_demo_stack(database_path, media_root)
    store = stack.demo_store
    ensure_demo_credential(stack.auth_stores.for_store(store))
    report = verify_demo_runtime(stack, base)
    if not report.credential_ok:
        stack.close()
        raise DemoRuntimeError(
            "the local demonstration credential did not authenticate; "
            "run `make demo-reset` to rebuild the demo runtime"
        )
    return stack, report


def verify_demo_runtime(stack: StorefrontStack, root: Path | None = None) -> DemoRuntimeReport:
    """Read back what the runtime actually contains; never a claim from configuration."""

    store = stack.demo_store
    scope = store.scope
    committed = load_pitch_catalog(DEFAULT_DEMO_DATASET_PATH, store.configuration())
    summary = stack.catalog_repository.index_summary(
        scope, model_id=MODEL_ID, model_revision=MODEL_REVISION, dimensions=EMBEDDING_DIMENSIONS
    )
    managed = stack.catalog_repository.managed_items(
        scope, model_id=MODEL_ID, model_revision=MODEL_REVISION, dimensions=EMBEDDING_DIMENSIONS
    )
    authenticated = stack.auth_stores.for_store(store).authenticate(DEMO_USERNAME, DEMO_PASSWORD)
    base = demo_runtime_root(root)
    database_path, media_root = demo_runtime_paths(base)
    return DemoRuntimeReport(
        root=base,
        database_path=database_path,
        media_root=media_root,
        store_id=scope.store_id,
        items=stack.catalog_repository.item_count(scope),
        ready_embeddings=summary.ready,
        uploaded_items=sum(1 for item in managed if item.merchant_upload),
        baseline_items=len(committed.items),
        credential_ok=authenticated.identity is not None,
    )


def reset_demo_runtime(root: Path | None = None) -> DemoRuntimeReport:
    """Delete only the dedicated demo runtime root and rebuild the pristine baseline."""

    base = demo_runtime_root(root)
    active = demo_runtime_in_use(base)
    if active is not None:
        raise DemoRuntimeError(
            f"the Form & Field demo (pid {active}) is still using {base}; stop it first"
        )
    if base.exists():
        shutil.rmtree(base)
    stack, report = bootstrap_demo_runtime(base)
    try:
        if not report.is_pristine_baseline:
            raise DemoRuntimeError(
                "reset did not produce the pristine committed baseline: "
                f"{report.items} items, {report.ready_embeddings} ready embeddings, "
                f"{report.uploaded_items} local uploads (expected {report.baseline_items})"
            )
    finally:
        stack.close()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m apps.web.demo_runtime",
        description=(
            "Recreate the dedicated local Form & Field demo runtime and exit. "
            "Touches only that isolated, ignored directory."
        ),
    )
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_DEMO_RUNTIME_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        report = reset_demo_runtime(arguments.runtime_root)
    except DemoRuntimeError as error:
        print(f"demo reset refused: {error}", file=sys.stderr, flush=True)
        return 1
    print(report.describe("Form & Field demo reset"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
