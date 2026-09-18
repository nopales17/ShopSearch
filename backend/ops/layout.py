"""On-disk layout of one operator backup snapshot.

Both the backup and restore commands share these names so a snapshot is one
self-describing directory: the consistent SQLite image plus a mirrored copy of the
store-scoped content-addressed media tree.
"""

from __future__ import annotations

DATABASE_FILENAME = "database.sqlite3"
MEDIA_DIRNAME = "media"
