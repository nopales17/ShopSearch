"""Real runtime health checks for the deployed process (S10).

The check is deliberately narrow and generic: it asks the persistence boundary for a
trivial read and the media adapter whether its root is usable. It never reports
filesystem paths, SQL errors, store data or secrets, and it writes no telemetry —
health probing is operational, not behavioral, traffic.
"""

from __future__ import annotations

import logging
from typing import Callable

DATABASE_UNAVAILABLE = "database unavailable"
MEDIA_UNAVAILABLE = "media unavailable"


class RuntimeHealth:
    """Database and media reachability behind one generic status."""

    def __init__(
        self,
        *,
        database_check: Callable[[], None],
        media_check: Callable[[], None],
        logger: logging.Logger | None = None,
    ) -> None:
        self._database_check = database_check
        self._media_check = media_check
        self._logger = logger

    def check(self) -> tuple[bool, str]:
        """Return `(healthy, body)` with a generic, non-disclosing body."""

        try:
            self._database_check()
        except Exception:  # any failure is an unhealthy database, never a leaked error
            self._log(DATABASE_UNAVAILABLE)
            return False, DATABASE_UNAVAILABLE
        try:
            self._media_check()
        except Exception:
            self._log(MEDIA_UNAVAILABLE)
            return False, MEDIA_UNAVAILABLE
        return True, "ok"

    def _log(self, reason: str) -> None:
        if self._logger is not None:
            self._logger.warning("health check failed", extra={"reason": reason})
