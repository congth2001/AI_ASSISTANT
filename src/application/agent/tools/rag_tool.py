from typing import Any, Dict, List
import asyncio

from src.application.agent.tools.base import BaseTool
from src.application.services.context_builder import ContextBuilder
from src.application.use_cases.search_document_use_case import SearchDocumentsUseCase
from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.entities.message import Message
from src.application.agent.tools.result import ToolResult


class RAGTool(BaseTool):
    name = "rag_tool"
    description = (
        "Search relevant business documents in Milvus vector store "
        "and build a structured context dict for LLM consumption."
    )

    def __init__(
        self,
        search_use_case: SearchDocumentsUseCase,
        context_builder: ContextBuilder,
    ):
        self.search_use_case = search_use_case
        self.context_builder = context_builder

    async def run(
        self,
        analyzed: AnalyzedQuery,
        messages: List[Message],
        current_query: str,
        **kwargs,
    ) -> ToolResult:
        context = await asyncio.to_thread(
            self.run_sync, analyzed, messages, current_query
        )
        return ToolResult(
            success=True,
            has_data=bool(context.get("has_data", False)),
            content=context.get("retrieved_text", ""),
            metadata={"context": context},
        )

    def run_sync(
        self,
        analyzed: AnalyzedQuery,
        messages: List[Message],
        current_query: str,
    ) -> Dict[str, Any]:
        search_result = self.search_use_case.execute_analyzed(analyzed)
        return self.context_builder.build_context(
            search_result=search_result,
            messages=messages,
            current_query=current_query,
        )
