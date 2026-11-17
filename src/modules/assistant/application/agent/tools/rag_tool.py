from typing import Any, Dict, List
import asyncio

from src.modules.assistant.application.agent.tools.base_tool import BaseTool
from src.modules.assistant.application.services.context_builder import ContextBuilder
from src.modules.assistant.application.use_cases.search_documents_use_case import SearchDocumentsUseCase
from src.modules.assistant.domain.entities.analyzed_query import AnalyzedQuery
from src.modules.conversations.domain.entities.message import Message
from src.modules.assistant.application.agent.tools.tool_result import ToolResult


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
        context = self.context_builder.build_context(
            search_result=search_result,
            messages=messages,
            current_query=current_query,
        )
        error_code = getattr(search_result, "error_code", None)
        if error_code:
            # Retrieval failed (e.g. vector store down): do not let the answer read
            # as "no matching documents".
            context["has_data"] = False
            context["retrieval_error"] = error_code
            context["fallback_warning"] = (
                "Không truy xuất được tài liệu do lỗi kho dữ liệu vector; "
                "không thể kết luận là không có tài liệu liên quan."
            )
        return context
