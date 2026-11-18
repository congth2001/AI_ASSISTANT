import logging

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InterfaceError
from sqlalchemy.ext.asyncio import AsyncEngine

from src.modules.assistant.domain.errors import (
    SQLDatabaseConnectionLostError,
    SQLDatabaseFailureError,
    SQLQueryRejectedError,
    SQLQueryTimeoutError,
)
from src.modules.assistant.domain.ports.i_sql_executor import ISQLExecutor

logger = logging.getLogger(__name__)

# SQLSTATE classes that describe a problem in the query itself: syntax/access rule
# (42), data exception (22), integrity (23), feature not supported (0A),
# cardinality violation (21). The LLM can repair these.
_QUERY_ERROR_CLASSES = frozenset({"21", "22", "23", "0A", "42"})
# Timeouts and cancellations: statement_timeout, lock_timeout, idle-in-transaction.
_TIMEOUT_SQLSTATES = frozenset({"57014", "55P03", "25P03"})
_MAX_ERROR_CHARS = 300


class PostgresSQLExecutor(ISQLExecutor):
    """
    Executes read-only SQL queries against PostgreSQL.
    Used by the LLM-to-SQL pipeline (TextToSQLUseCase).

    Failures are translated so callers can tell them apart:
    - ``SQLValidationError`` for a defect in the query (sanitized message, repairable);
    - ``OperationTimeoutError`` for statement/lock timeouts;
    - ``ExternalServiceError`` for connection and other infrastructure failures.
    """

    STATEMENT_TIMEOUT_MS = 15_000
    LOCK_TIMEOUT_MS = 2_000
    IDLE_IN_TRANSACTION_TIMEOUT_MS = 20_000
    MAX_ROWS = 1000  # keep in sync with SQLService's outer LIMIT

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def execute_sql(self, sql: str) -> tuple[list, list[str]]:
        """Run a SELECT query and return (rows, column_names)."""
        try:
            return await self._run(sql)
        except DBAPIError as exc:
            # InterfaceError subclasses DBAPIError, so it must be checked here,
            # not in a later except clause that would never run.
            if isinstance(exc, InterfaceError) or exc.connection_invalidated:
                logger.warning("SQL execution lost its database connection")
                raise SQLDatabaseConnectionLostError() from exc
            raise self._translate(exc) from exc

    async def _run(self, sql: str) -> tuple[list, list[str]]:
        async with self._engine.connect() as conn:
            async with conn.begin():
                # Defense in depth: the generated query executes in a read-only,
                # time-bounded transaction even if validation misses something.
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                await conn.execute(
                    text(f"SET LOCAL statement_timeout = {self.STATEMENT_TIMEOUT_MS}")
                )
                await conn.execute(text(f"SET LOCAL lock_timeout = {self.LOCK_TIMEOUT_MS}"))
                await conn.execute(
                    text(
                        "SET LOCAL idle_in_transaction_session_timeout = "
                        f"{self.IDLE_IN_TRANSACTION_TIMEOUT_MS}"
                    )
                )
                result = await conn.execute(text(sql))
                rows = result.fetchmany(self.MAX_ROWS)
                cols = list(result.keys())
                return rows, cols

    @staticmethod
    def _translate(exc: DBAPIError) -> Exception:
        original = exc.orig
        sqlstate = str(getattr(original, "sqlstate", "") or "")
        if sqlstate in _TIMEOUT_SQLSTATES:
            logger.warning("SQL execution timed out (sqlstate=%s)", sqlstate)
            return SQLQueryTimeoutError()
        if sqlstate[:2] in _QUERY_ERROR_CLASSES and not exc.connection_invalidated:
            # Only the primary message: DETAIL/HINT/CONTEXT can quote row values and
            # SQLAlchemy's own text embeds the statement and driver internals.
            # The adapter wraps the asyncpg exception, which keeps the server's message.
            driver_error = getattr(original, "__cause__", None) or original
            primary = str(getattr(driver_error, "message", None) or driver_error).strip()
            primary = " ".join(primary.split())[:_MAX_ERROR_CHARS] or "lỗi truy vấn"
            return SQLQueryRejectedError(sqlstate=sqlstate, detail=primary)
        logger.error("SQL execution failed in the database layer (sqlstate=%s)", sqlstate or "?")
        return SQLDatabaseFailureError()
