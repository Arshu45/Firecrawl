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
import threading
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.pool

from config.settings import DATABASE_URL

logger = logging.getLogger(__name__)


_global_pool = None
_pool_lock = threading.Lock()


def _truncate(value: Any, limit: int = 400) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


def get_pool():
    global _global_pool
    if _global_pool is None:
        with _pool_lock:
            if _global_pool is None:
                _global_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=10,
                    dsn=DATABASE_URL,
                )
                logger.info("global DB connection pool created")
    return _global_pool

class DBClient:
    """
    Thread-safe database client backed by psycopg2 ThreadedConnectionPool.
    All queries use RealDictCursor so rows come back as plain dicts.
    """

    def __init__(self):
        self._pool = get_pool()
        logger.info("DBClient initialized")

    # ── Internal helpers ───────────────────────────────────────

    def _get_conn(self):
        # ThreadedConnectionPool requires an explicit key so it can track
        # which connection belongs to which caller.  Using the thread ID
        # avoids the "trying to put unkeyed connection" PoolError that
        # occurs when key=None is stored but indistinguishable from "not found".
        thread_id = threading.get_ident()
        logger.info("DB connection checkout | thread_id=%s", thread_id)
        return self._pool.getconn(key=thread_id)

    def _put_conn(self, conn):
        thread_id = threading.get_ident()
        self._pool.putconn(conn, key=thread_id)
        logger.info("DB connection returned | thread_id=%s", thread_id)

    # ── Public query methods ───────────────────────────────────

    def execute(self, query: str, params: tuple | dict = ()) -> list[dict]:
        """
        Run a SELECT query and return all rows as a list of dicts.
        """
        conn = self._get_conn()
        try:
            logger.info(
                "DB execute start | kind=SELECT | query=%s | params=%s",
                _truncate(query),
                _truncate(params),
            )
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                rows = [dict(row) for row in cur.fetchall()]
                logger.info(
                    "DB execute complete | rows=%d | preview=%s",
                    len(rows),
                    _truncate(rows),
                )
                return rows
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
            logger.info(
                "DB execute_one start | query=%s | params=%s",
                _truncate(query),
                _truncate(params),
            )
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                result = dict(row) if row else None
                logger.info("DB execute_one complete | row=%s", _truncate(result))
                return result
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
            logger.info(
                "DB execute_write start | query=%s | params=%s",
                _truncate(query),
                _truncate(params),
            )
            with conn.cursor() as cur:
                cur.execute(query, params)
                conn.commit()
                logger.info("DB execute_write complete | rowcount=%d", cur.rowcount)
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
            logger.info(
                "DB execute_write_returning start | query=%s | params=%s",
                _truncate(query),
                _truncate(params),
            )
            with conn.cursor() as cur:
                cur.execute(query, params)
                conn.commit()
                row = cur.fetchone()
                result = row[0] if row else None
                logger.info("DB execute_write_returning complete | value=%s", _truncate(result))
                return result
        except Exception as e:
            conn.rollback()
            logger.error(f"execute_write_returning() failed: {e}")
            raise
        finally:
            self._put_conn(conn)

    # ── Lifecycle ──────────────────────────────────────────────

    def close(self):
        """Used to permanently shut down the pool on application exit."""
        global _global_pool
        if _global_pool is not None:
            _global_pool.closeall()
            _global_pool = None
            logger.info("DB connection pool closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # We NO LONGER close the entire pool on exit.
        # Connections are safely returned via _put_conn inside execute().
        return False
