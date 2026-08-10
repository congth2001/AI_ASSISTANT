from src.application.agent.tools.base import BaseTool
from src.application.use_cases.analytics_use_case import AnalyticsUseCase
from src.domain.entities.analyzed_query import AnalyzedQuery
from typing import Tuple
from src.application.agent.tools.result import ToolResult

class TextToSQLTool(BaseTool):
    name = "text_to_sql"
    description = (
        "Convert a natural language business question to SQL "
        "and execute it against the PostgreSQL analytics database."
    )

    def __init__(
        self, 
        analytics_use_case: AnalyticsUseCase,
        ):
        self.analytics_use_case = analytics_use_case

    async def run(self, analyzed: AnalyzedQuery, **kwargs) -> ToolResult:
        sql_queries, content, success, has_data, error_code = await self.analytics_use_case.execute(analyzed)
        return ToolResult(
            success=success,
            has_data=has_data,
            content=content,
            error_code=error_code,
            metadata={"sql_queries": sql_queries},
        )
