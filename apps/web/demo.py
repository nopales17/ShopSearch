"""Explicit developer/demo entry point for the Form & Field pitch storefront.

Production startup (`python -m apps.web.wsgi`) never provisions a store. This command
is the only path that seeds the committed pitch-demo store and imports its dataset,
embeddings and retrieval-index artifact, so the demo stays runnable on purpose without
being a side effect of normal startup.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from apps.web.storefront import open_demo_stack
from apps.web.wsgi import WaitressServer, create_pitch_app
from backend.adapters.clip import MODEL_ID, MODEL_REVISION
from backend.platform import operational_log
from backend.platform.paths import DEFAULT_DATABASE_PATH, DEFAULT_MEDIA_ROOT
from backend.runtime.config import RuntimeConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Form & Field pitch demo.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--media-root", type=Path, default=DEFAULT_MEDIA_ROOT)
    arguments = parser.parse_args()

    logger = operational_log.configure_operational_logging()
    stack = open_demo_stack(arguments.database, arguments.media_root)
    store_id = stack.demo_store.store_id
    config = RuntimeConfig.for_local_development(
        database_path=arguments.database,
        media_root=arguments.media_root,
        store_ids=(store_id,),
        bind_host=arguments.host,
        port=arguments.port,
    )
    server = WaitressServer(
        create_pitch_app(stack=stack, storefronts={store_id}, logger=logger),
        host=arguments.host,
        port=arguments.port,
        config=config,
    )
    print(
        f"Pitch demo ready: http://{arguments.host}:{server.server_port} "
        f"(store {store_id}, model {MODEL_ID}@{MODEL_REVISION[:8]})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
