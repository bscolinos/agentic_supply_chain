"""
SingleStore database service layer for the NERVE project.

Provides connection pooling, query execution with timing, retry logic,
and health checks. All query results include execution time in ms for
the UI latency badge.
"""

import os
import time
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import threading

import singlestoredb as s2
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_CONFIG = {
    "host": os.getenv("SINGLESTORE_HOST", "127.0.0.1"),
    "port": int(os.getenv("SINGLESTORE_PORT", "3306")),
    "user": os.getenv("SINGLESTORE_USER", "root"),
    "password": os.getenv("SINGLESTORE_PASSWORD", "password"),
    "database": os.getenv("SINGLESTORE_DATABASE", "nerve"),
}

MAX_RETRIES = 3
BACKOFF_BASE = 0.5  # seconds; retry waits 0.5, 1.0, 2.0

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class QueryResult:
    """Container returned by every read query."""

    data: list[dict[str, Any]]
    row_count: int
    execution_time_ms: float


@dataclass
class WriteResult:
    """Container returned by every write query."""

    rows_affected: int
    last_insert_id: int | None
    execution_time_ms: float


@dataclass
class DBStatus:
    """Connection health report."""

    connected: bool
    latency_ms: float | None = None
    error: str | None = None
    pool_size: int = 0
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Thread-local connection manager
# ---------------------------------------------------------------------------

_thread_local = threading.local()


def _get_thread_conn():
    """Return this thread's connection, creating one if needed."""
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        conn = s2.connect(**DB_CONFIG)
        _thread_local.conn = conn
    return conn


def _invalidate_thread_conn():
    """Discard this thread's connection so the next call gets a fresh one."""
    conn = getattr(_thread_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _thread_local.conn = None


# Keep ConnectionPool as a no-op facade so Database.connect/close still work.
class ConnectionPool:
    _instance: "ConnectionPool | None" = None

    @classmethod
    def get_instance(cls) -> "ConnectionPool":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        _invalidate_thread_conn()

    def close(self) -> None:
        _invalidate_thread_conn()


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


@contextmanager
def get_connection(*, commit: bool = True):
    """
    Yield a per-thread SingleStore connection.  Each OS thread (including
    thread-pool workers spawned by run_in_executor) gets its own dedicated
    connection, so concurrent callers never share state.

    Usage::

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
    """
    conn = _get_thread_conn()
    try:
        yield conn
        if commit:
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            _invalidate_thread_conn()
        raise


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------


def _retry(fn, *args, **kwargs):
    """
    Execute *fn* with up to MAX_RETRIES retries and exponential backoff.

    On connection-level errors the pool is reset so the next attempt gets a
    fresh connection.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "DB attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc
            )
            # Discard the thread-local connection so the next attempt gets a fresh one.
            _invalidate_thread_conn()
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------


def _run_query(sql: str, params: tuple | list | dict | None = None) -> QueryResult:
    """Internal: execute a SELECT and return rows as dicts with timing."""
    with get_connection(commit=False) as conn:
        cursor = conn.cursor()
        start = time.perf_counter()
        cursor.execute(sql, params or ())
        rows = cursor.fetchall()
        elapsed_ms = (time.perf_counter() - start) * 1000

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        data = [dict(zip(columns, row)) for row in rows]

        logger.debug("Query completed in %.2f ms  |  %d rows", elapsed_ms, len(data))
        return QueryResult(data=data, row_count=len(data), execution_time_ms=round(elapsed_ms, 2))


def _run_write(sql: str, params: tuple | list | dict | None = None) -> WriteResult:
    """Internal: execute an INSERT / UPDATE / DELETE with timing."""
    with get_connection() as conn:
        cursor = conn.cursor()
        start = time.perf_counter()
        cursor.execute(sql, params or ())
        elapsed_ms = (time.perf_counter() - start) * 1000

        rows_affected = cursor.rowcount
        last_id = cursor.lastrowid

        logger.debug("Write completed in %.2f ms  |  %d rows affected", elapsed_ms, rows_affected)
        return WriteResult(
            rows_affected=rows_affected,
            last_insert_id=last_id,
            execution_time_ms=round(elapsed_ms, 2),
        )


def execute_query(sql: str, params: tuple | list | dict | None = None) -> QueryResult:
    """
    Execute a read query with retry logic and return results as a list of
    dicts plus execution time (ms).

    Returns a ``QueryResult`` with ``.data``, ``.row_count``, and
    ``.execution_time_ms``.
    """
    return _retry(_run_query, sql, params)


def execute_write(sql: str, params: tuple | list | dict | None = None) -> WriteResult:
    """
    Execute a write query (INSERT / UPDATE / DELETE) with retry logic.

    Returns a ``WriteResult`` with ``.rows_affected``, ``.last_insert_id``,
    and ``.execution_time_ms``.
    """
    return _retry(_run_write, sql, params)


# ---------------------------------------------------------------------------
# Async wrappers (for FastAPI route handlers)
# ---------------------------------------------------------------------------


async def async_execute_query(sql: str, params: tuple | list | dict | None = None) -> QueryResult:
    """Async-compatible wrapper around ``execute_query`` for FastAPI."""
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, execute_query, sql, params)


async def async_execute_write(sql: str, params: tuple | list | dict | None = None) -> WriteResult:
    """Async-compatible wrapper around ``execute_write`` for FastAPI."""
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, execute_write, sql, params)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def get_status() -> DBStatus:
    """
    Probe the database and return a ``DBStatus`` health report.

    This is intentionally lightweight -- it runs ``SELECT 1`` and measures
    the round-trip latency.
    """
    try:
        result = execute_query("SELECT 1 AS ok")
        return DBStatus(
            connected=True,
            latency_ms=result.execution_time_ms,
            pool_size=5,
            details={"host": DB_CONFIG["host"], "database": DB_CONFIG["database"]},
        )
    except Exception as exc:
        return DBStatus(
            connected=False,
            error=str(exc),
            details={"host": DB_CONFIG["host"], "database": DB_CONFIG["database"]},
        )


# ---------------------------------------------------------------------------
# Database facade — simplified interface used by routes and services
# ---------------------------------------------------------------------------


class Database:
    """
    High-level facade over the connection pool.

    Routes and services call ``db.execute_query(sql, params)`` which returns
    ``(list[dict], float)`` — the result rows and execution time in ms.
    """

    def connect(self) -> None:
        """Warm a connection on the main thread (called at startup)."""
        _get_thread_conn()
        logger.info("Database connected to %s/%s", DB_CONFIG["host"], DB_CONFIG["database"])

    def close(self) -> None:
        """Shutdown the pool."""
        ConnectionPool.reset()

    def execute_query(
        self, sql: str, params: tuple | list | dict | None = None
    ) -> tuple[list[dict[str, Any]], float]:
        """Execute a SELECT and return (rows_as_dicts, execution_time_ms)."""
        result = execute_query(sql, params)
        return result.data, result.execution_time_ms

    def execute_write(
        self, sql: str, params: tuple | list | dict | None = None
    ) -> WriteResult:
        """Execute INSERT/UPDATE/DELETE and return WriteResult."""
        return execute_write(sql, params)
