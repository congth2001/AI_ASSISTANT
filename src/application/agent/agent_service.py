from typing import AsyncGenerator, Dict, Any, List
import asyncio
from uuid import uuid4

from src.application.agent.graph.builder import build_agent_graph, build_context_graph
from src.application.agent.graph.state import AgentState
from src.application.agent.tools.rag_tool import RAGTool
from src.application.agent.tools.text_to_sql import TextToSQLTool
from src.application.services.intent_classifier import IntentClassifier
from src.application.services.query_analyzer import QueryAnalyzer
from src.application.services.query_contextualizer import QueryContextualizer
from src.domain.entities.message import Message
from src.domain.interfaces.i_llm_service import ILLMService


class AgentService:
    """Thin wrapper around the compiled LangGraph agent.

    Builds two graphs at construction time:
    - _graph: full pipeline including generate_response (used by ChatUseCase.execute)
    - _context_graph: tool-only pipeline (used by ChatUseCase.execute_stream before token streaming)
    """

    def __init__(
        self,
        classifier: IntentClassifier,
        query_analyzer: QueryAnalyzer,
        contextualizer: QueryContextualizer,
        text_to_sql_tool: TextToSQLTool,
        rag_tool: RAGTool,
        llm_service: ILLMService,
        checkpointer: Any = None,
    ):
        self._llm_service = llm_service
        self._graph = build_agent_graph(
            classifier=classifier,
            query_analyzer=query_analyzer,
            contextualizer=contextualizer,
            text_to_sql_tool=text_to_sql_tool,
            rag_tool=rag_tool,
            llm_service=llm_service,
            checkpointer=checkpointer,
        )
        self._context_graph = build_context_graph(
            classifier=classifier,
            query_analyzer=query_analyzer,
            contextualizer=contextualizer,
            text_to_sql_tool=text_to_sql_tool,
            rag_tool=rag_tool,
            checkpointer=checkpointer,
        )

    def _make_initial_state(self, query: str, messages: List[Message]) -> AgentState:
        return {
            "query": query,
            "messages": messages,
            "route": None,
            "analyzed": None,
            "tool_name": None,
            "tool_result": None,
            "context": None,
            "sql_query": None,
            "tool_success": None,
            "tool_error_code": None,
            "trace_id": str(uuid4()),
            "node_metrics": [],
            "tool_calls": [],
            "citations": [],
            "plan": [],
            "attempted_routes": [],
            "iteration": 0,
            "max_iterations": 3,
            "needs_clarification": False,
            "clarification_question": None,
            "evaluation": None,
            "response_attempts": 0,
            "awaiting_approval": False,
            "pending_action": None,
            "response": None,
        }

    async def invoke(
        self, query: str, messages: List[Message], thread_id: str | None = None
    ) -> AgentState:
        config = {"configurable": {"thread_id": f"full:{thread_id or uuid4()}"}}
        return await self._graph.ainvoke(self._make_initial_state(query, messages), config=config)

    async def invoke_for_context(
        self, query: str, messages: List[Message], thread_id: str | None = None
    ) -> AgentState:
        """Run routing + tool execution only; skips generate_response.
        Returns the final AgentState with context populated, ready for LLM streaming.
        """
        config = {"configurable": {"thread_id": f"context:{thread_id or uuid4()}"}}
        return await self._context_graph.ainvoke(
            self._make_initial_state(query, messages), config=config
        )

    async def stream_response(self, query: str, context: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Delegate token streaming to the underlying LLM service."""
        async with asyncio.timeout(60):
            async for token in self._llm_service.stream_response(query, context):
                yield token
