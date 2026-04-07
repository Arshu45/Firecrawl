"""
Layer 3 — Database Client
PostgreSQL connection pool + query helpers via psycopg2.
All queries use parameterised statements — never raw string interpolation.
"""

import logging
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.pool

from config.settings import DATABASE_URL

logger = logging.getLogger(__name__)


class DBClient:
    """
    Thin wrapper around a psycopg2 SimpleConnectionPool.
    Rows are returned as dicts (RealDictCursor).
    """

    def __init__(self):
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set in .env")
        self._pool = psycopg2.pool.SimpleConnectionPool(
            1, 10,
            dsn=DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        logger.info("DB connection pool initialised (min=1, max=10)")

    # ── Internal helpers ────────────────────────────────────────────────

    def _conn(self):
        return self._pool.getconn()

    def _put(self, conn):
        self._pool.putconn(conn)

    # ── Public interface ────────────────────────────────────────────────

    def execute(self, query: str, params: tuple | dict | None = None) -> list[dict]:
        """Run a SELECT — returns list of row dicts."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            conn.rollback()
            logger.error(f"DB execute error: {e}")
            raise
        finally:
            self._put(conn)

    def execute_one(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Run a SELECT — returns single row dict or None."""
        rows = self.execute(query, params)
        return rows[0] if rows else None

    def execute_write(self, query: str, params: tuple | dict | None = None) -> int:
        """Run an INSERT/UPDATE/DELETE — returns rowcount."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                conn.commit()
                return cur.rowcount
        except Exception as e:
            conn.rollback()
            logger.error(f"DB write error: {e}")
            raise
        finally:
            self._put(conn)

    def execute_returning(self, query: str, params: tuple | dict | None = None) -> dict | None:
        """Run INSERT ... RETURNING — returns the returned row."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                conn.commit()
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"DB execute_returning error: {e}")
            raise
        finally:
            self._put(conn)

    def close(self):
        """Close all connections in the pool."""
        self._pool.closeall()
        logger.info("DB connection pool closed")
