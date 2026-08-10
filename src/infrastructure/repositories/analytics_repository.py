from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class AnalyticsRepository:
    """
    Executes raw SQL analytics queries against PostgreSQL.
    Used by the LLM-to-SQL pipeline (AnalyticsUseCase).
    """

    STATEMENT_TIMEOUT_MS = 15_000

    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    async def execute_sql(self, sql: str) -> tuple[list, list[str]]:
        """
        Run a SELECT query and return (rows, column_names).
        Caller is responsible for catching exceptions.
        """
        async with self._engine.connect() as conn:
            async with conn.begin():
                # Defense in depth: the generated query executes in a read-only,
                # time-bounded transaction even if validation misses something.
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                await conn.execute(
                    text(f"SET LOCAL statement_timeout = {self.STATEMENT_TIMEOUT_MS}")
                )
                result = await conn.execute(text(sql))
                rows = result.fetchall()
                cols = list(result.keys())
                return rows, cols
