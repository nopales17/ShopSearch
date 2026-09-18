"""Founder-provisioned store registry CLI.

python -m backend.stores.cli --database PATH seed-demo
python -m backend.stores.cli --database PATH create --config STORE.json [--domain HOST]
python -m backend.stores.cli --database PATH list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from backend.platform.paths import DEFAULT_DATABASE_PATH, DEFAULT_DEMO_STORE_PATH
from backend.stores.config import load_store_config
from backend.stores.repository import DuplicateHostnameError, StoreRepository
from backend.stores.seed import seed_store
from backend.stores.validation import StoreValidationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.stores.cli",
        description="Provision founder-authored stores and hostnames.",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="create a store from a configuration file")
    create.add_argument("--config", type=Path, required=True)
    create.add_argument(
        "--domain",
        action="append",
        default=[],
        help="additional hostname to register (repeatable)",
    )

    seed = commands.add_parser("seed-demo", help="seed the committed demo store")
    seed.add_argument("--config", type=Path, default=DEFAULT_DEMO_STORE_PATH)

    commands.add_parser("list", help="list provisioned stores")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        with StoreRepository.open(arguments.database) as repository:
            if arguments.command == "create":
                store, domains = load_store_config(arguments.config)
                created = repository.create_store(store, (*domains, *arguments.domain))
                print(f"created {created.store_id}")
            elif arguments.command == "seed-demo":
                store = seed_store(repository, arguments.config)
                print(f"seeded {store.store_id}")
            else:
                for store in repository.list_stores():
                    hostnames = ", ".join(repository.domains_for(store.scope))
                    print(f"{store.store_id}\t{store.display_name}\t{hostnames}")
    except (DuplicateHostnameError, StoreValidationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
