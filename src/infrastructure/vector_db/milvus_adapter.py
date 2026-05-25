import logging
from typing import List, Optional, Dict, Any
from pymilvus import MilvusClient, DataType
from src.domain.interfaces.i_vector_db import IVectorDB

logger = logging.getLogger(__name__)

_OUTPUT_FIELDS = ["doc_id", "doc_type", "text", "year", "month", "customer_id", "co_no", "doanh_thu"]
_RRF_K = 60  # RRF constant — higher = less penalty for lower ranks


class MilvusAdapter(IVectorDB):
    def __init__(
        self,
        host: str = "localhost",
        port: int = 19530,
        collection_name: str = "business_data",
        vector_dimension: int = 1024,
        metric_type: str = "COSINE"
    ):
        self.collection_name = collection_name
        self.vector_dimension = vector_dimension
        self.metric_type = metric_type

        self._client = MilvusClient(uri=f"http://{host}:{port}")
        logger.info(f"Connected to Milvus at {host}:{port}")
        self._ensure_collection()

    def _ensure_collection(self):
        if not self._client.has_collection(self.collection_name):
            self._create_collection()
            logger.info(f"Created new collection: {self.collection_name}")
        else:
            logger.info(f"Using existing collection: {self.collection_name}")

    def _create_collection(self):
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("doc_id",      DataType.VARCHAR,      is_primary=True, max_length=128)
        schema.add_field("doc_type",    DataType.VARCHAR,      max_length=32)
        schema.add_field("text",        DataType.VARCHAR,      max_length=4096)
        schema.add_field("embedding",   DataType.FLOAT_VECTOR, dim=self.vector_dimension)
        schema.add_field("year",        DataType.INT16)
        schema.add_field("month",       DataType.INT8)
        schema.add_field("customer_id", DataType.VARCHAR,      max_length=128)
        schema.add_field("co_no",       DataType.BOOL)
        schema.add_field("doanh_thu",   DataType.DOUBLE)

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name  = "embedding",
            metric_type = "COSINE",
            index_type  = "HNSW",
            params      = {"M": 16, "efConstruction": 200},
        )

        self._client.create_collection(
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
                filter          = f'doc_id == "{id}"',
            )
            logger.info(f"Deleted embedding with id: {id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting embedding: {e}")
            return False

    # ─────────────────────────────
    # Read operations
    # ─────────────────────────────

    def query(self, filter: str, output_fields: List[str] = None, limit: int = 1) -> Optional[List[Dict]]:
        try:
            results = self._client.query(
                collection_name = self.collection_name,
                filter          = filter,
                output_fields   = output_fields,
                limit           = limit,
            )
            return results if results else None
        except Exception as e:
            logger.error(f"Error querying: {e}")
            return None

    def search_similar(
        self,
        query_vector  : List[float],
        top_k         : int = 5,
        filter        : str = "",
        output_fields : Optional[List[str]] = None,
        search_params : Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        try:
            sp = search_params or {"metric_type": "COSINE", "params": {"ef": 100}}
            results = self._client.search(
                collection_name = self.collection_name,
                data            = [query_vector],
                anns_field      = "embedding",
                search_params   = sp,
                limit           = top_k,
                filter          = filter or None,
                output_fields   = output_fields or _OUTPUT_FIELDS,
            )
            return self._format_hits(results[0])
        except Exception as e:
            logger.error(f"Error searching vectors: {e}")
            return []

    def keyword_search(
        self,
        query_text    : str,
        top_k         : int = 5,
        filter        : str = "",
        case_sensitive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Term-frequency keyword search. Pre-filters via Milvus filter expression."""
        try:
            entities = self._client.query(
                collection_name = self.collection_name,
                filter          = filter or "",
                output_fields   = _OUTPUT_FIELDS,
                limit           = 1000,
            )

            terms  = query_text.split() if case_sensitive else query_text.lower().split()
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
            logger.error(f"Error in keyword search: {e}")
            return []

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
        try:
            sp = {"metric_type": "COSINE", "params": {"ef": ef}}
            vector_results  = self.search_similar(query_vector, top_k * 2, filter=filter, search_params=sp)
            keyword_results = self.keyword_search(query_text,   top_k * 2, filter=filter)
            merged = self._rrf_merge(vector_results, keyword_results, top_k, vector_weight, keyword_weight)
            logger.info(f"Hybrid search found {len(merged)} results (v={len(vector_results)}, k={len(keyword_results)})")
            return merged
        except Exception as e:
            logger.error(f"Error in hybrid search: {e}")
            return []

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
