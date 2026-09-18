"""Persistence substrate selected by ADR-0004.

This package is part of the persistence layer: it is one of the only places that
may import `sqlite3` or hand out raw connections. Repository modules in
`backend/*` own SQL; web, view, search-ranking and tooling code receive
repository objects instead.
"""
