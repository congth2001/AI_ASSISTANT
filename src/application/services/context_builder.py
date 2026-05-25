from typing import List, Dict, Any, Optional

from src.domain.entities.message import Message
from src.domain.entities.search_document_result import SearchDocumentsResult
from src.domain.entities.time_filter import TimeFilter


class ContextBuilder:
    """
    Build a structured context dict consumed by the LLM adapter.

    Input : SearchDocumentsResult (retrieved docs + analyzed query + fallback flag)
            + conversation history + current query
    Output: Dict passed directly to LLMService.generate_response()
    """

    MAX_DOCS             = 5     # top-N docs by relevance score
    MAX_CHARS_PER_DOC    = 800   # truncation limit per doc to control tokens
    MAX_HISTORY_MESSAGES = 10    # recent turns included in context

    def __init__(
        self,
        max_docs            : int = MAX_DOCS,
        max_chars_per_doc   : int = MAX_CHARS_PER_DOC,
        max_history_messages: int = MAX_HISTORY_MESSAGES,
    ):
        self.max_docs             = max_docs
        self.max_chars_per_doc    = max_chars_per_doc
        self.max_history_messages = max_history_messages

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    def build_context(
        self,
        search_result: SearchDocumentsResult,
        messages    : List[Message],
        current_query: str,
    ) -> Dict[str, Any]:
        aq   = search_result.analyzed_query
        docs = self._format_documents(search_result)

        return {
            # ── Retrieved business data ──────────────────────────────────
            "retrieved_documents": docs,
            "retrieved_text"     : self._build_retrieved_text(docs),
            "has_data"           : bool(docs),

            # ── Query analysis metadata ──────────────────────────────────
            "intent"       : aq.primary_intent.value,
            "intents"      : [i.value for i in aq.intents],
            "customer_name": aq.customer_name,
            "category_name": aq.category_name,
            "product_name" : aq.product_name,
            "invoice_id"   : aq.invoice_id,
            "time_filter"  : self._format_time_filter(aq.time_filter),

            # ── Fallback awareness ───────────────────────────────────────
            "used_fallback"  : search_result.used_fallback,
            "fallback_warning": self._build_fallback_warning(search_result),

            # ── Conversation context ─────────────────────────────────────
            "conversation_history": self._format_history(messages),
            "current_query"       : current_query,
        }

    def extract_keywords(self, text: str) -> List[str]:
        """Simple keyword extraction — removes Vietnamese/English stop words."""
        stop_words = {
            "là", "và", "của", "cho", "trong", "với", "từ", "có",
            "các", "những", "được", "này", "đó",
        }
        words    = text.lower().split()
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        return list(dict.fromkeys(keywords))  # deduplicate, preserve order

    # ─────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────

    def _format_documents(
        self, search_result: SearchDocumentsResult
    ) -> List[Dict[str, Any]]:
        """Select top-N docs by score, truncate long texts."""
        top = sorted(search_result.results, key=lambda r: r.score, reverse=True)
        top = top[: self.max_docs]

        result = []
        for r in top:
            text = r.text
            if len(text) > self.max_chars_per_doc:
                text = text[: self.max_chars_per_doc] + "..."
            result.append({
                "doc_id"  : r.doc_id,
                "doc_type": r.doc_type,
                "text"    : text,
                "score"   : round(r.score, 4),
                "metadata": r.metadata,
            })
        return result

    def _build_retrieved_text(self, docs: List[Dict[str, Any]]) -> str:
        """Concatenate docs into a single block for system prompt injection."""
        if not docs:
            return ""

        parts = []
        for i, doc in enumerate(docs, 1):
            meta         = doc["metadata"]
            header_parts = [f"[Tài liệu {i}]"]

            if meta.get("month") and meta.get("year"):
                header_parts.append(f"Tháng {meta['month']}/{meta['year']}")
            elif meta.get("year"):
                header_parts.append(f"Năm {meta['year']}")

            if meta.get("customer_id"):
                header_parts.append(f"KH: {meta['customer_id']}")
            if meta.get("doc_type"):
                header_parts.append(f"Loại: {meta['doc_type']}")

            header = " | ".join(header_parts)
            parts.append(f"{header}\n{doc['text']}")

        return "\n\n".join(parts)

    def _build_fallback_warning(
        self, search_result: SearchDocumentsResult
    ) -> Optional[str]:
        """Return a Vietnamese warning string when fallback was triggered."""
        if not search_result.used_fallback:
            return None

        aq    = search_result.analyzed_query
        tf    = aq.time_filter
        parts = []

        if tf.month and tf.year:
            parts.append(f"tháng {tf.month}/{tf.year}")
        elif tf.quarter and tf.year:
            parts.append(f"quý {tf.quarter}/{tf.year}")
        elif tf.month:
            parts.append(f"tháng {tf.month}")
        elif tf.year:
            parts.append(f"năm {tf.year}")

        if aq.customer_name:
            parts.append(f"khách hàng '{aq.customer_name}'")
        if aq.category_name:
            parts.append(f"danh mục '{aq.category_name}'")

        if parts:
            criteria = " và ".join(parts)
            return (
                f"Không tìm thấy dữ liệu chính xác cho {criteria}. "
                "Kết quả bên dưới là dữ liệu gần nhất tìm được — "
                "có thể không khớp hoàn toàn với yêu cầu."
            )
        return (
            "Không tìm thấy dữ liệu khớp chính xác. "
            "Kết quả bên dưới là dữ liệu gần nhất tìm được."
        )

    def _format_time_filter(self, tf: TimeFilter) -> Dict[str, Any]:
        return {"year": tf.year, "month": tf.month, "quarter": tf.quarter}

    def _format_history(self, messages: List[Message]) -> List[Dict[str, Any]]:
        recent = messages[-self.max_history_messages :]
        return [
            {
                "role"     : msg.role,
                "content"  : msg.content,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
            }
            for msg in recent
        ]
