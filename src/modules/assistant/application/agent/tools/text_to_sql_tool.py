from src.modules.assistant.application.agent.tools.base_tool import BaseTool
from src.modules.assistant.application.use_cases.text_to_sql_use_case import TextToSQLUseCase
from src.modules.assistant.domain.entities.analyzed_query import AnalyzedQuery
from src.modules.assistant.application.agent.tools.tool_result import ToolResult


class TextToSQLTool(BaseTool):
    name = "text_to_sql"
    description = (
        "Convert a natural language business question to SQL "
        "and execute it against the PostgreSQL analytics database."
    )

    def __init__(self, text_to_sql_use_case: TextToSQLUseCase):
        self.text_to_sql_use_case = text_to_sql_use_case

    async def run(self, analyzed: AnalyzedQuery, **kwargs) -> ToolResult:
        sql_queries, content, success, has_data, error_code = (
            await self.text_to_sql_use_case.execute(analyzed)
        )
        return ToolResult(
            success=success,
            has_data=has_data,
            content=content,
            error_code=error_code,
            metadata={"sql_queries": sql_queries},
        )
