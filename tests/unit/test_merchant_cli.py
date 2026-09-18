from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from backend.auth import cli
from backend.auth.repository import MerchantNotFoundError
from backend.auth.service import AuthStores
from backend.platform.paths import DEFAULT_DEMO_STORE_PATH
from backend.stores.repository import StoreRepository
from backend.stores.seed import seed_store
from tests.unit.test_merchant_auth import FAST_ITERATIONS, ScriptedReader


class MerchantCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database_path = Path(self.directory.name) / "shopsearch.sqlite3"
        with StoreRepository.open(self.database_path) as stores:
            self.store = seed_store(stores, DEFAULT_DEMO_STORE_PATH)

    def run_cli(self, *arguments: str, passwords: list[str] | None = None) -> tuple[int, str]:
        reader = ScriptedReader(iter(passwords)) if passwords else None
        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = cli.main(
                [
                    "--database",
                    str(self.database_path),
                    "--store-id",
                    self.store.store_id,
                    *arguments,
                ],
                password_reader=reader,
            )
        return code, output.getvalue() + errors.getvalue()

    def auth(self):
        stores = AuthStores.open(self.database_path, iterations=FAST_ITERATIONS)
        self.addCleanup(stores.close)
        return stores.for_store(self.store)

    def test_cli_creates_lists_disables_and_rejects_duplicates(self) -> None:
        code, output = self.run_cli(
            "create", "--username", "Carol", passwords=["first-password", "first-password"]
        )
        self.assertEqual(code, 0)
        self.assertIn("created carol", output)
        auth = self.auth()
        self.assertIsNotNone(auth.authenticate("carol", "first-password").identity)

        code, output = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("carol", output)

        code, _ = self.run_cli("disable", "--username", "carol")
        self.assertEqual(code, 0)
        self.assertIsNone(self.auth().authenticate("carol", "first-password").identity)

        code, output = self.run_cli(
            "create", "--username", "CAROL", passwords=["second-password", "second-password"]
        )
        self.assertEqual(code, 1)
        self.assertIn("error:", output)

    def test_cli_reset_revokes_existing_sessions(self) -> None:
        auth = self.auth()
        identity = auth.create_merchant("alice", "first-password")
        issued = auth.start_session(identity)
        self.assertIsNotNone(auth.identify(issued.token))

        code, output = self.run_cli(
            "reset", "--username", "alice", passwords=["second-password", "second-password"]
        )
        self.assertEqual(code, 0)
        self.assertIn("revoked 1 sessions", output)
        refreshed = self.auth()
        self.assertIsNone(refreshed.identify(issued.token))
        self.assertIsNone(refreshed.authenticate("alice", "first-password").identity)
        self.assertIsNotNone(refreshed.authenticate("alice", "second-password").identity)

    def test_cli_rejects_mismatched_empty_and_unknown_targets(self) -> None:
        code, _ = self.run_cli(
            "create", "--username", "bob", passwords=["first-password", "second-password"]
        )
        self.assertEqual(code, 1)
        code, _ = self.run_cli("create", "--username", "bob", passwords=["", ""])
        self.assertEqual(code, 1)
        self.assertEqual(self.auth().list_merchants(), ())
        code, _ = self.run_cli("reset", "--username", "nobody", passwords=["x", "x"])
        self.assertEqual(code, 1)
        with self.assertRaises(MerchantNotFoundError):
            self.auth().reset_password("nobody", "x")
        code, output = self.run_cli("list")
        self.assertEqual((code, output.strip()), (0, ""))

    def test_cli_never_accepts_a_password_argument(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(
                [
                    "--database",
                    str(self.database_path),
                    "--store-id",
                    self.store.store_id,
                    "create",
                    "--username",
                    "alice",
                    "--password",
                    "hunter2",
                ]
            )

    def test_cli_requires_a_known_store(self) -> None:
        reader = ScriptedReader(iter(["x", "x"]))
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(
                [
                    "--database",
                    str(self.database_path),
                    "--store-id",
                    "absent-store",
                    "create",
                    "--username",
                    "alice",
                ],
                password_reader=reader,
            )
        self.assertEqual(code, 1)
        self.assertIn("error:", errors.getvalue())
