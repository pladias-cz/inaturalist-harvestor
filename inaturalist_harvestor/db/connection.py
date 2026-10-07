"""PostgreSQL connection management."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg


class Database:
    """Owns the database URL and hands out connections."""

    def __init__(self, url: str) -> None:
        self._url = url

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        """Yield a raw connection (autocommit is disabled)."""
        with psycopg.connect(self._url) as conn:
            yield conn

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        """Yield a connection committed on success, rolled back on error."""
        with psycopg.connect(self._url) as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
