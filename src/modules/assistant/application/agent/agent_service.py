from typing import AsyncGenerator, Dict, Any, List
import asyncio
import logging
from uuid import uuid4

from src.modules.assistant.application.agent.graph.builder import build_agent_graph, build_context_graph
from src.modules.assistant.application.agent.graph.state import AgentState
from src.modules.assistant.application.agent.tools.rag_tool import RAGTool
from src.modules.assistant.application.agent.tools.text_to_sql_tool import TextToSQLTool
from src.modules.assistant.application.services.intent_classifier import IntentClassifier
from src.modules.assistant.application.services.query_analyzer import QueryAnalyzer
from src.modules.assistant.application.services.query_contextualizer import QueryContextualizer
from src.modules.conversations.domain.entities.message import Message
from src.modules.assistant.domain.errors import AgentOperationTimeout
from src.modules.assistant.domain.ports.i_llm_service import ILLMService

logger = logging.getLogger(__name__)

# Upper bounds for a whole graph run. Individual nodes carry their own timeouts
# (see graph/nodes.py); these caps stop a chain of slow nodes and retries from
# holding a request open indefinitely.
# Must stay above analyze_query (15s) + the slowest tool node (hybrid, 95s).
CONTEXT_GRAPH_TIMEOUT_SECONDS = 150
FULL_GRAPH_TIMEOUT_SECONDS = 240
STREAM_RESPONSE_TIMEOUT_SECONDS = 60
# Guests only get short small-talk answers; keep their token spend low.
GUEST_COMPLETION_TOKENS = 1536


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
        self._classifier = classifier
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
            "needs_clarification": False,
            "clarification_question": None,
            "evaluation": None,
            "response_attempts": 0,
            "response": None,
        }

    async def _run_graph(
        self,
        graph: Any,
        prefix: str,
        query: str,
        messages: List[Message],
        conversation_id: str | None,
        timeout_seconds: float,
    ) -> AgentState:
        """Run one turn on a thread that is unique to this turn.

        History comes from PostgreSQL, not from the checkpointer, so a shared
        per-conversation thread only accumulated checkpoints in RAM. A fresh
        thread per turn is deleted from the checkpointer once the turn ends.
        """
        thread_id = f"{prefix}:{conversation_id or 'anon'}:{uuid4().hex}"
        config = {"configurable": {"thread_id": thread_id}}
        try:
            async with asyncio.timeout(timeout_seconds):
                return await graph.ainvoke(self._make_initial_state(query, messages), config=config)
        except AgentOperationTimeout:
            raise
        except TimeoutError as exc:
            raise AgentOperationTimeout(operation=f"{prefix}_graph") from exc
        finally:
            await self._discard_thread(graph, thread_id)

    @staticmethod
    async def _discard_thread(graph: Any, thread_id: str) -> None:
        checkpointer = getattr(graph, "checkpointer", None)
        if not checkpointer:
            return
        try:
            await checkpointer.adelete_thread(thread_id)
        except Exception:
            logger.warning("Could not delete agent checkpoint", extra={"thread_id": thread_id}, exc_info=True)

    async def invoke(
        self, query: str, messages: List[Message], thread_id: str | None = None
    ) -> AgentState:
        return await self._run_graph(
            self._graph, "full", query, messages, thread_id, FULL_GRAPH_TIMEOUT_SECONDS
        )

    async def invoke_for_context(
        self, query: str, messages: List[Message], thread_id: str | None = None
    ) -> AgentState:
        """Run routing + tool execution only; skips generate_response.
        Returns the final AgentState with context populated, ready for LLM streaming.
        """
        return await self._run_graph(
            self._context_graph, "context", query, messages, thread_id, CONTEXT_GRAPH_TIMEOUT_SECONDS
        )

    async def stream_response(self, query: str, context: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Delegate token streaming to the underlying LLM service.

        The time budget covers only waiting for the provider. The deadline is
        never held across ``yield``: time the consumer (a slow SSE client) spends
        between tokens is not counted, and a deadline cannot fire while the task
        is suspended outside this generator, where it would surface as a plain
        cancellation (client disconnect) instead of ``AgentOperationTimeout``.
        """
        loop = asyncio.get_running_loop()
        remaining = float(STREAM_RESPONSE_TIMEOUT_SECONDS)
        tokens = self._llm_service.stream_response(query, context).__aiter__()
        try:
            while True:
                started = loop.time()
                try:
                    async with asyncio.timeout(max(remaining, 0.0)):
                        token = await tokens.__anext__()
                except StopAsyncIteration:
                    return
                except TimeoutError as exc:
                    raise AgentOperationTimeout(operation="stream_response") from exc
                remaining -= loop.time() - started
                yield token
        finally:
            aclose = getattr(tokens, "aclose", None)
            if aclose is not None:
                await aclose()

    async def classify_route(self, query: str) -> str:
        """Classify a query without executing SQL, RAG, or any data tool."""
        return await self._classifier.classify(query)

    async def stream_stateless_conversation(self, query: str) -> AsyncGenerator[str, None]:
        """Answer without history or tools. Used for guests as a hard data boundary."""
        context = {
            "conversation_history": [],
            "current_query": query,
            "intent": "conversation",
            "has_data": False,
            "used_fallback": False,
            "fallback_warning": None,
            "sources": [],
            "response_mode": "conversation",
            "max_completion_tokens": GUEST_COMPLETION_TOKENS,
        }
        async for token in self.stream_response(query, context):
            yield token
