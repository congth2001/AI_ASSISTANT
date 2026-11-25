import logging
from threading import Lock
from typing import List, Optional, Dict, Any
from pymilvus import MilvusClient as PyMilvusClient, DataType
from src.modules.assistant.domain.errors import UnsupportedVectorMetricError, VectorStoreQueryError
from src.modules.assistant.domain.ports.i_vector_db import IVectorDB

logger = logging.getLogger(__name__)

_OUTPUT_FIELDS = ["doc_id", "doc_type", "text", "year", "month", "customer_id", "co_no", "doanh_thu"]
_RRF_K = 60  # RRF constant — higher = less penalty for lower ranks
_METRIC_TYPES = frozenset({"L2", "IP", "COSINE"})
_EMBEDDING_FIELD = "embedding"

# keyword_search KHÔNG dùng index: kéo tối đa chừng này bản ghi (mỗi bản ghi tới 4KB `text`)
# về Python để chấm điểm. Khi chạm trần, các bản ghi ngoài trần bị bỏ qua (thứ tự do Milvus quyết định)
# nên điểm từ khóa chỉ là xấp xỉ; luôn có log cảnh báo. Collection lớn hơn cần full-text/BM25
# (cần trường sparse trong schema + re-index, hiện chưa có).
_KEYWORD_SCAN_LIMIT = 1000

_CONTROL_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def quote_filter_value(value: object) -> str:
    """Biến giá trị thành literal chuỗi an toàn trong biểu thức filter Milvus ("...").

    Escape backslash và dấu nháy kép; xuống dòng/tab được escape, ký tự điều khiển còn lại bị bỏ.
    Luôn dùng hàm này thay vì nội suy f'..."{x}"...' để chuỗi do người dùng/LLM cung cấp
    không phá cú pháp hay chèn thêm điều kiện.
    """
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    out = []
    for ch in text:
        if ch in _CONTROL_ESCAPES:
            out.append(_CONTROL_ESCAPES[ch])
        elif ord(ch) < 32 or ord(ch) == 127:
            continue
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


class MilvusClient(IVectorDB):
    def __init__(
        self,
        host: str = "localhost",
        port: int = 19530,
        collection_name: str = "business_data",
        vector_dimension: int = 1024,
        metric_type: str = "COSINE"
    ):
        metric_type = str(metric_type).upper()
        if metric_type not in _METRIC_TYPES:
            raise UnsupportedVectorMetricError(metric_type=metric_type)
        self.collection_name = collection_name
        self.vector_dimension = vector_dimension
        # Configured metric for new collections; replaced by the existing index's metric on
        # connect, because a search must use the metric the index was built with.
        self.metric_type = metric_type

        # SQL-only and conversational requests must not require a live vector DB.
        self._uri = f"http://{host}:{port}"
        self._connection = None
        self._connection_lock = Lock()

    @property
    def _client(self):
        with self._connection_lock:
            if self._connection is None:
                client = PyMilvusClient(uri=self._uri, timeout=10)
                try:
                    self._ensure_collection(client)
                except Exception:
                    client.close()
                    raise
                self._connection = client
                logger.info("Connected to Milvus")
            return self._connection

    def _ensure_collection(self, client):
        if not client.has_collection(self.collection_name):
            self._create_collection(client)
            logger.info(f"Created new collection: {self.collection_name}")
        else:
            logger.info(f"Using existing collection: {self.collection_name}")
            self._adopt_index_metric(client)

    def _adopt_index_metric(self, client) -> None:
        try:
            index = client.describe_index(self.collection_name, _EMBEDDING_FIELD) or {}
        except Exception:
            logger.warning(
                "Could not read the metric of index %r on %s; using configured %s",
                _EMBEDDING_FIELD, self.collection_name, self.metric_type, exc_info=True,
            )
            return
        actual = str(index.get("metric_type") or "").upper()
        if actual in _METRIC_TYPES and actual != self.metric_type:
            logger.warning(
                "Collection %s was indexed with %s but vector_db.metric_type is %s; searching "
                "with %s. Recreate the collection to change the metric.",
                self.collection_name, actual, self.metric_type, actual,
            )
            self.metric_type = actual

    def _create_collection(self, client):
        schema = PyMilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("doc_id",      DataType.VARCHAR,      is_primary=True, max_length=128)
        schema.add_field("doc_type",    DataType.VARCHAR,      max_length=32)
        schema.add_field("text",        DataType.VARCHAR,      max_length=4096)
        schema.add_field(_EMBEDDING_FIELD, DataType.FLOAT_VECTOR, dim=self.vector_dimension)
        schema.add_field("year",        DataType.INT16)
        schema.add_field("month",       DataType.INT8)
        schema.add_field("customer_id", DataType.VARCHAR,      max_length=128)
        schema.add_field("co_no",       DataType.BOOL)
        schema.add_field("doanh_thu",   DataType.DOUBLE)

        index_params = PyMilvusClient.prepare_index_params()
        index_params.add_index(
            field_name  = _EMBEDDING_FIELD,
            metric_type = self.metric_type,
            index_type  = "HNSW",
            params      = {"M": 16, "efConstruction": 200},
        )

        client.create_collection(
            collection_name = self.collection_name,
            schema          = schema,
            index_params    = index_params,
        )

    # ─────────────────────────────
    # Write operations
    # ─────────────────────────────

    def upsert(self, collection_name: str, data: List[Dict[str, Any]]) -> bool:
        try:
            self._client.upsert(collection_name=collection_name, data=data)
            return True
        except Exception as e:
            logger.error(f"Error upserting data: {e}")
            return False

    def store_embedding(self, id: str, vector: List[float], metadata: Optional[Dict[str, Any]] = None) -> bool:
        try:
            metadata = metadata or {}
            data = [{
                "doc_id"     : id,
                "doc_type"   : str(metadata.get("doc_type", "")),
                "text"       : str(metadata.get("text", ""))[:4096],
                "embedding"  : vector,
                "year"       : int(metadata.get("year", 0)),
                "month"      : int(metadata.get("month", 0)),
                "customer_id": str(metadata.get("customer_id", "")),
                "co_no"      : bool(metadata.get("co_no", False)),
                "doanh_thu"  : float(metadata.get("doanh_thu", 0.0)),
            }]
            self._client.upsert(collection_name=self.collection_name, data=data)
            logger.info(f"Stored embedding with id: {id}")
            return True
        except Exception as e:
            logger.error(f"Error storing embedding: {e}")
            return False

    def delete_embedding(self, id: str) -> bool:
        try:
            self._client.delete(
                collection_name = self.collection_name,
                filter          = f"doc_id == {quote_filter_value(id)}",
            )
            logger.info(f"Deleted embedding with id: {id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting embedding: {e}")
            return False

    # ─────────────────────────────
    # Read operations
    # ─────────────────────────────

    def query(self, filter: str, output_fields: Optional[List[str]] = None, limit: int = 1) -> List[Dict[str, Any]]:
        """Truy vấn theo filter. Trả list (rỗng nếu không có bản ghi); ném VectorStoreQueryError khi Milvus lỗi."""
        try:
            results = self._client.query(
                collection_name = self.collection_name,
                filter          = filter,
                output_fields   = output_fields,
                limit           = limit,
            )
            return list(results) if results else []
        except Exception as e:
            logger.error("Error querying Milvus: %s", e)
            raise VectorStoreQueryError(operation="query", collection=self.collection_name) from e

    def query_all(
        self,
        filter       : str,
        output_fields: Optional[List[str]] = None,
        batch_size   : int = 1000,
    ) -> List[Dict[str, Any]]:
        """Quét TOÀN BỘ bản ghi khớp filter bằng query iterator (đầy đủ, không phụ thuộc thứ tự).

        Thứ tự kết quả không được bảo đảm; caller tự sort. Ném VectorStoreQueryError khi Milvus lỗi.
        """
        rows: List[Dict[str, Any]] = []
        iterator = None
        try:
            iterator = self._client.query_iterator(
                collection_name = self.collection_name,
                batch_size      = batch_size,
                filter          = filter or "",
                output_fields   = output_fields,
            )
            while True:
                batch = iterator.next()
                if not batch:
                    break
                rows.extend(batch)
        except Exception as e:
            logger.error("Error scanning Milvus with query iterator: %s", e)
            raise VectorStoreQueryError(operation="query_all", collection=self.collection_name) from e
        finally:
            if iterator is not None:
                try:
                    iterator.close()
                except Exception:
                    logger.debug("Failed to close Milvus query iterator", exc_info=True)
        return rows

    def search_similar(
        self,
        query_vector  : List[float],
        top_k         : int = 5,
        filter        : str = "",
        output_fields : Optional[List[str]] = None,
        search_params : Optional[Dict[str, Any]] = None,
        ef            : int = 100,
    ) -> List[Dict[str, Any]]:
        try:
            client = self._client  # connecting also settles self.metric_type
            sp = search_params or {"metric_type": self.metric_type, "params": {"ef": ef}}
            results = client.search(
                collection_name = self.collection_name,
                data            = [query_vector],
                anns_field      = _EMBEDDING_FIELD,
                search_params   = sp,
                limit           = top_k,
                filter          = filter or None,
                output_fields   = output_fields or _OUTPUT_FIELDS,
            )
            return self._format_hits(results[0])
        except Exception as e:
            logger.error("Error searching vectors: %s", e)
            raise VectorStoreQueryError(operation="search_similar", collection=self.collection_name) from e

    def keyword_search(
        self,
        query_text    : str,
        top_k         : int = 5,
        filter        : str = "",
        case_sensitive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Term-frequency keyword search. Pre-filters via Milvus filter expression.

        Giới hạn: quét tối đa ``_KEYWORD_SCAN_LIMIT`` bản ghi khớp filter rồi chấm điểm trong Python
        (không có index từ khóa); chạm trần thì log cảnh báo. Ném VectorStoreQueryError khi Milvus lỗi.
        """
        try:
            entities = self._client.query(
                collection_name = self.collection_name,
                filter          = filter or "",
                output_fields   = _OUTPUT_FIELDS,
                limit           = _KEYWORD_SCAN_LIMIT,
            )
        except Exception as e:
            logger.error("Error in keyword search: %s", e)
            raise VectorStoreQueryError(operation="keyword_search", collection=self.collection_name) from e

        entities = entities or []
        if len(entities) >= _KEYWORD_SCAN_LIMIT:
            logger.warning(
                "Keyword search reached scan cap (%d rows, filter=%r); results are approximate",
                _KEYWORD_SCAN_LIMIT, filter,
            )

        try:
            terms = query_text.split() if case_sensitive else query_text.lower().split()
            scored = []

            for entity in entities:
                content = entity.get("text", "")
                text_cmp = content if case_sensitive else content.lower()

                score      = 0.0
                term_count = 0
                for term in terms:
                    if term in text_cmp:
                        score += text_cmp.count(term)
                        if text_cmp.startswith(term):
                            score += 5
                        term_count += 1

                if len(text_cmp) > 0:
                    score /= len(text_cmp)

                match_ratio = term_count / len(terms) if terms else 0
                score *= (1 + match_ratio)

                if score > 0:
                    scored.append({
                        "id"      : entity.get("doc_id"),
                        "score"   : score,
                        "content" : content,
                        "metadata": {
                            "doc_type"   : entity.get("doc_type"),
                            "year"       : entity.get("year"),
                            "month"      : entity.get("month"),
                            "customer_id": entity.get("customer_id"),
                            "co_no"      : entity.get("co_no"),
                            "doanh_thu"  : entity.get("doanh_thu"),
                        },
                    })

            scored.sort(key=lambda x: x["score"], reverse=True)
            logger.info(f"Keyword search found {len(scored)} results")
            return scored[:top_k]

        except Exception as e:
            logger.error("Error scoring keyword search results: %s", e)
            raise VectorStoreQueryError(operation="keyword_search", collection=self.collection_name) from e

    # ─────────────────────────────
    # Hybrid search (vector + keyword via RRF)
    # ─────────────────────────────

    def hybrid_search(
        self,
        query_vector  : List[float],
        query_text    : str,
        top_k         : int = 5,
        filter        : str = "",
        ef            : int = 100,
        vector_weight : float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        Combines vector search and keyword search via Reciprocal Rank Fusion (RRF).
        Both searches use the same Milvus filter expression.
        ef controls HNSW recall quality for the vector branch.
        """
        # Lỗi Milvus (VectorStoreQueryError) được để lan ra: rỗng nghĩa là "không có kết quả", không phải "lỗi".
        vector_results  = self.search_similar(
            query_vector, top_k * 2, filter=filter, search_params=None, ef=ef
        )
        keyword_results = self.keyword_search(query_text,   top_k * 2, filter=filter)
        merged = self._rrf_merge(vector_results, keyword_results, top_k, vector_weight, keyword_weight)
        logger.info(f"Hybrid search found {len(merged)} results (v={len(vector_results)}, k={len(keyword_results)})")
        return merged

    # ─────────────────────────────
    # Internal helpers
    # ─────────────────────────────

    def _format_hits(self, hits) -> List[Dict[str, Any]]:
        results = []
        for hit in hits:
            entity = hit["entity"]
            results.append({
                "id"      : entity.get("doc_id"),
                "score"   : hit["distance"],
                "content" : entity.get("text", ""),
                "metadata": {
                    "doc_type"   : entity.get("doc_type"),
                    "year"       : entity.get("year"),
                    "month"      : entity.get("month"),
                    "customer_id": entity.get("customer_id"),
                    "co_no"      : entity.get("co_no"),
                    "doanh_thu"  : entity.get("doanh_thu"),
                },
            })
        return results

    def _rrf_merge(
        self,
        vector_results : List[Dict],
        keyword_results: List[Dict],
        top_k          : int,
        vector_weight  : float,
        keyword_weight : float,
    ) -> List[Dict[str, Any]]:
        """
        Reciprocal Rank Fusion: score(d) = Σ weight_i / (K + rank_i(d))
        Rank-based fusion avoids needing to normalize scores across different scales.
        """
        scores: Dict[str, Dict] = {}

        for rank, r in enumerate(vector_results):
            doc_id = r["id"]
            scores[doc_id] = {
                "rrf" : vector_weight / (_RRF_K + rank + 1),
                "data": r,
            }

        for rank, r in enumerate(keyword_results):
            doc_id = r["id"]
            rrf_k  = keyword_weight / (_RRF_K + rank + 1)
            if doc_id in scores:
                scores[doc_id]["rrf"] += rrf_k
            else:
                scores[doc_id] = {"rrf": rrf_k, "data": r}

        sorted_items = sorted(scores.values(), key=lambda x: x["rrf"], reverse=True)
        return [{**item["data"], "score": item["rrf"]} for item in sorted_items[:top_k]]

    # ─────────────────────────────
    # Admin
    # ─────────────────────────────

    def drop_collection(self) -> bool:
        try:
            if self._client.has_collection(self.collection_name):
                self._client.drop_collection(self.collection_name)
                logger.info(f"Dropped collection: {self.collection_name}")
                return True
            logger.warning(f"Collection {self.collection_name} does not exist")
            return False
        except Exception as e:
            logger.error(f"Failed to drop collection: {str(e)}")
            return False

    def get_collection_stats(self) -> Dict[str, Any]:
        try:
            stats = self._client.get_collection_stats(self.collection_name)
            return {
                "num_entities"    : int(stats.get("row_count", 0)),
                "collection_name" : self.collection_name,
                "vector_dimension": self.vector_dimension,
            }
        except Exception as e:
            logger.error(f"Failed to get collection stats: {str(e)}")
            return {}
