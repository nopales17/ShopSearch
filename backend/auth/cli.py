"""Founder CLI for store-scoped merchant accounts.

    python -m backend.auth.cli --store-id pitch-demo create --username alice
    python -m backend.auth.cli --store-id pitch-demo disable --username alice
    python -m backend.auth.cli --store-id pitch-demo reset --username alice
    python -m backend.auth.cli --store-id pitch-demo list

Passwords are read from an interactive prompt (never from an argument), so they do not
enter shell history. Resetting a credential revokes that merchant's existing sessions.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import Callable, Sequence

from backend.auth.repository import DuplicateUsernameError, MerchantNotFoundError
from backend.auth.service import AuthStores
from backend.platform.paths import DEFAULT_DATABASE_PATH
from backend.stores.repository import StoreNotFoundError, StoreRepository
from contracts.store import StoreScope

DEFAULT_STORE_ID = "pitch-demo"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.auth.cli",
        description="Provision founder-managed merchant accounts for one store.",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--store-id", default=DEFAULT_STORE_ID)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="create a merchant account")
    create.add_argument("--username", required=True)

    disable = commands.add_parser("disable", help="disable a merchant account")
    disable.add_argument("--username", required=True)

    reset = commands.add_parser("reset", help="replace a credential and revoke sessions")
    reset.add_argument("--username", required=True)

    commands.add_parser("list", help="list this store's merchant usernames")
    return parser


def read_new_password(reader: Callable[[str], str]) -> str:
    first = reader("Password: ")
    second = reader("Repeat password: ")
    if first != second:
        raise ValueError("passwords do not match")
    if not first:
        raise ValueError("password must not be empty")
    return first


def main(
    argv: Sequence[str] | None = None, *, password_reader: Callable[[str], str] | None = None
) -> int:
    arguments = build_parser().parse_args(argv)
    reader = password_reader or getpass.getpass
    try:
        with StoreRepository.open(arguments.database) as stores:
            store = stores.get_store(StoreScope(arguments.store_id))
            with AuthStores.open(arguments.database) as auth_stores:
                auth = auth_stores.for_store(store)
                if arguments.command == "create":
                    identity = auth.create_merchant(arguments.username, read_new_password(reader))
                    print(f"created {identity.username} in {identity.store_id}")
                elif arguments.command == "disable":
                    auth.disable_merchant(arguments.username)
                    print(f"disabled {arguments.username} in {store.store_id}")
                elif arguments.command == "reset":
                    revoked = auth.reset_password(arguments.username, read_new_password(reader))
                    print(
                        f"reset credential for {arguments.username} in {store.store_id}; "
                        f"revoked {revoked} sessions"
                    )
                else:
                    for identity in auth.list_merchants():
                        print(f"{identity.username}\t{identity.merchant_id}")
    except (
        DuplicateUsernameError,
        MerchantNotFoundError,
        StoreNotFoundError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
