"""Explicit interactive developer/demo entry point for the Form & Field storefront.

Production startup (`python -m apps.web.wsgi`) never provisions a store and never
enables demo mutation. This command is the only path that seeds the committed
pitch-demo store, imports its dataset and embeddings, provisions the local
demonstration credential, and passes the explicit in-memory interactive-demo
capability into the merchant composition.

It runs from the dedicated ignored runtime root (`data/local/form-and-field-demo/`), so
a demo upload or `make demo-reset` can never touch the generic local platform state,
another store or a configured production path. An existing runtime is preserved:
re-running this command keeps the user's local uploads and mutations.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from apps.web.demo_runtime import (
    DEMO_PASSWORD,
    DEMO_USERNAME,
    bootstrap_demo_runtime,
    clear_demo_process,
    record_demo_process,
)
from apps.web.manage import InteractiveDemo
from apps.web.wsgi import WaitressServer, create_pitch_app
from backend.adapters.clip import MODEL_ID, MODEL_REVISION, ClipEncoder
from backend.platform import operational_log
from backend.platform.paths import DEFAULT_DEMO_RUNTIME_ROOT, demo_runtime_paths
from backend.runtime.config import RuntimeConfig
from backend.search.indexer import EmbeddingIndexer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the interactive local Form & Field demo.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_DEMO_RUNTIME_ROOT)
    arguments = parser.parse_args()

    logger = operational_log.configure_operational_logging()
    stack, report = bootstrap_demo_runtime(arguments.runtime_root)
    store_id = stack.demo_store.store_id
    database_path, media_root = demo_runtime_paths(report.root)
    config = RuntimeConfig.for_local_development(
        database_path=database_path,
        media_root=media_root,
        store_ids=(store_id,),
        bind_host=arguments.host,
        port=arguments.port,
    )
    # One encoder serves both customer retrieval and the explicit demo indexing action.
    encoder = ClipEncoder()
    indexer = EmbeddingIndexer(
        stack.catalog_repository,
        stack.image_store,
        encoder,
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
    )
    server = WaitressServer(
        create_pitch_app(
            stack=stack,
            storefronts={store_id},
            encoder=encoder,
            logger=logger,
            interactive_demo=InteractiveDemo(DEMO_USERNAME, DEMO_PASSWORD),
            index_store=indexer.run,
        ),
        host=arguments.host,
        port=arguments.port,
        config=config,
    )
    record_demo_process(report.root, os.getpid())
    origin = f"http://{arguments.host}:{server.server_port}"
    print(f"Form & Field storefront: {origin}/", flush=True)
    print(f"Merchant sign-in: {origin}/manage/login", flush=True)
    print(
        f"Local demonstration credential: {DEMO_USERNAME} / {DEMO_PASSWORD} "
        "(local demo only; not a production account)",
        flush=True,
    )
    print(report.describe("Demo runtime ready"), flush=True)
    print(f"Store {store_id}, model {MODEL_ID}@{MODEL_REVISION[:8]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        clear_demo_process(report.root)


if __name__ == "__main__":
    main()
