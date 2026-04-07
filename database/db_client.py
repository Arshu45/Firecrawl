"""
Layer 3 — Database Client
Thin wrapper around psycopg2 with connection pooling.

Usage:
    from database.db_client import DBClient
    db = DBClient()
    rows = db.execute("SELECT * FROM promotions WHERE category = %s", ("Fashion",))
    db.close()

Or use as a context manager:
    with DBClient() as db:
        rows = db.execute(...)
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
    Thread-safe database client backed by psycopg2 SimpleConnectionPool.
    All queries use RealDictCursor so rows come back as plain dicts.
    """

    _pool: psycopg2.pool.SimpleConnectionPool | None = None

    def __init__(self):
        if DBClient._pool is None:
            DBClient._pool = psycopg2.pool.SimpleConnectionPool(
                minconn = 1,
                maxconn = 10,
                dsn     = DATABASE_URL,
            )
            logger.info("DB connection pool created")

    # ── Internal helpers ───────────────────────────────────────

    def _get_conn(self):
        return DBClient._pool.getconn()

    def _put_conn(self, conn):
        DBClient._pool.putconn(conn)

    # ── Public query methods ───────────────────────────────────

    def execute(self, query: str, params: tuple | dict = ()) -> list[dict]:
        """
        Run a SELECT query and return all rows as a list of dicts.
        """
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            conn.rollback()
            logger.error(f"execute() failed: {e}\nQuery: {query}\nParams: {params}")
            raise
        finally:
            self._put_conn(conn)

    def execute_one(self, query: str, params: tuple | dict = ()) -> dict | None:
        """
        Run a SELECT query and return a single row as a dict, or None.
        """
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"execute_one() failed: {e}")
            raise
        finally:
            self._put_conn(conn)

    def execute_write(self, query: str, params: tuple | dict = ()) -> int:
        """
        Run an INSERT / UPDATE / DELETE and return affected row count.
        Auto-commits on success, rolls back on failure.
        """
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                conn.commit()
                return cur.rowcount
        except Exception as e:
            conn.rollback()
            logger.error(f"execute_write() failed: {e}")
            raise
        finally:
            self._put_conn(conn)

    def execute_write_returning(self, query: str, params: tuple | dict = ()) -> Any:
        """
        Run an INSERT ... RETURNING ... and return the first value.
        Useful for getting the new row id after insert.
        """
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                conn.commit()
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"execute_write_returning() failed: {e}")
            raise
        finally:
            self._put_conn(conn)

    # ── Lifecycle ──────────────────────────────────────────────

    def close(self):
        if DBClient._pool:
            DBClient._pool.closeall()
            DBClient._pool = None
            logger.info("DB connection pool closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
