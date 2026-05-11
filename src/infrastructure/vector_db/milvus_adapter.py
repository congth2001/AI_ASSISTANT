import logging
from typing import List, Optional, Dict, Any, Tuple
from pymilvus import Collection, connections, utility, FieldSchema, CollectionSchema, DataType
from src.domain.interfaces.i_vector_db import IVectorDB

logger = logging.getLogger(__name__)


class MilvusAdapter(IVectorDB):
    """Milvus implementation of vector database"""

    FACENET_VECTOR_DIMENSION = 512  # FaceNet embedding dimension
    MILVUS_METRIC_TYPE = "L2"  # L2 distance metric
    MILVUS_COLLECTION_NAME = "business_data"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 19530,
        collection_name: str = "business_data",
        vector_dimension: int = 512
    ):
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.vector_dimension = vector_dimension
        self._connection = None
        self._collection = None
        self._initialized = False

    async def _get_connection(self):
        """Get or create Milvus connection"""
        if self._connection is None:
            try:
                connections.connect(
                    alias="default",
                    host=self.host,
                    port=self.port
                )
                self._connection = connections.get_connection_addr("default")
                logger.info(f"Connected to Milvus at {self.host}:{self.port}")
            except Exception as e:
                logger.error(f"Failed to connect to Milvus: {str(e)}")
                raise

        return self._connection

    async def _get_collection(self) -> Collection:
        """Get or create collection"""
        if self._collection is None:
            try:
                await self._get_connection()

                # Check if collection exists
                if utility.has_collection(self.collection_name):
                    self._collection = Collection(self.collection_name)
                    logger.info(f"Using existing collection: {self.collection_name}")
                else:
                    # Create collection if it doesn't exist
                    await self._create_collection_internal()
                    self._collection = Collection(self.collection_name)
                    logger.info(f"Created new collection: {self.collection_name}")

                self._collection.load()
                self._initialized = True

            except Exception as e:
                logger.error(f"Failed to get collection: {str(e)}")
                raise

        return self._collection

    async def _create_collection_internal(self) -> bool:
        """Create a new vector collection"""
        try:
            # Define collection schema
            fields = [
                FieldSchema(
                    name="id",
                    dtype=DataType.VARCHAR,
                    is_primary=True,
                    max_length=256
                ),
                FieldSchema(
                    name="vector",
                    dtype=DataType.FLOAT_VECTOR,
                    dim=self.vector_dimension
                ),
                FieldSchema(
                    name="content",
                    dtype=DataType.VARCHAR,
                    max_length=8192
                ),
                FieldSchema(
                    name="metadata_str",
                    dtype=DataType.VARCHAR,
                    max_length=4096
                )
            ]

            schema = CollectionSchema(
                fields=fields,
                description="Vector embeddings for business data with hybrid search support"
            )

            # Create collection
            collection = Collection(
                name=self.collection_name,
                schema=schema,
                using='default'
            )

            # Create index on vector field
            index_params = {
                "metric_type": self.MILVUS_METRIC_TYPE,
                "index_type": "IVF_FLAT",
                "params": {"nlist": 1024}
            }

            collection.create_index(
                field_name="vector",
                index_params=index_params
            )

            logger.info(f"Created collection: {self.collection_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create collection: {str(e)}")
            raise

    async def store_embedding(self, id: str, vector: List[float], metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Store an embedding vector with content"""
        try:
            collection = await self._get_collection()

            # Convert metadata to JSON string
            import json
            metadata = metadata or {}
            metadata_str = json.dumps(metadata)
            content = metadata.get('content', '')

            # Insert data with content field
            data = [
                [id],
                [vector],
                [content],
                [metadata_str]
            ]

            collection.insert(data)
            collection.flush()

            logger.info(f"Stored embedding with id: {id}")
            return True

        except Exception as e:
            logger.error(f"Error storing embedding: {e}")
            return False

    async def search_similar(self, query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for similar vectors using vector similarity only"""
        try:
            collection = await self._get_collection()

            # Search parameters
            search_params = {
                "metric_type": self.MILVUS_METRIC_TYPE,
                "params": {"nprobe": 10}
            }

            # Perform search
            results = collection.search(
                data=[query_vector],
                anns_field="vector",
                param=search_params,
                limit=top_k,
                output_fields=["id", "content", "metadata_str"]
            )

            # Format results
            formatted_results = []
            if results and len(results[0]) > 0:
                import json
                for hit in results[0]:
                    try:
                        metadata = json.loads(hit.entity.get("metadata_str", "{}"))
                    except:
                        metadata = {}

                    result = {
                        'id': hit.entity.get("id"),
                        'score': 1.0 / (1.0 + hit.distance),  # Convert L2 distance to similarity
                        'distance': hit.distance,
                        'content': hit.entity.get("content", ""),
                        'metadata': metadata
                    }
                    formatted_results.append(result)

            return formatted_results

        except Exception as e:
            logger.error(f"Error searching vectors: {e}")
            return []

    async def delete_embedding(self, id: str) -> bool:
        """Delete an embedding by ID"""
        try:
            collection = await self._get_collection()
            collection.delete(expr=f'id == "{id}"')
            collection.flush()

            logger.info(f"Deleted embedding with id: {id}")
            return True

        except Exception as e:
            logger.error(f"Error deleting embedding: {e}")
            return False

    async def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        top_k: int = 5,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3
    ) -> List[Dict[str, Any]]:
        """Hybrid search combining vector similarity and keyword matching"""
        try:
            # Get vector search results
            vector_results = await self.search_similar(query_vector, top_k * 2)

            # Get keyword search results
            keyword_results = await self.keyword_search(query_text, top_k * 2)

            # Create combined scoring
            combined_scores = {}

            # Add vector scores
            for result in vector_results:
                doc_id = result['id']
                vector_score = result['score']
                combined_scores[doc_id] = {
                    'vector_score': vector_score,
                    'keyword_score': 0.0,
                    'data': result
                }

            # Add/update keyword scores
            for result in keyword_results:
                doc_id = result['id']
                keyword_score = result['score']

                if doc_id in combined_scores:
                    combined_scores[doc_id]['keyword_score'] = keyword_score
                else:
                    combined_scores[doc_id] = {
                        'vector_score': 0.0,
                        'keyword_score': keyword_score,
                        'data': result
                    }

            # Calculate combined scores
            scored_results = []
            for doc_id, scores in combined_scores.items():
                combined_score = (
                    vector_weight * scores['vector_score'] +
                    keyword_weight * scores['keyword_score']
                )

                result_data = scores['data'].copy()
                result_data['combined_score'] = combined_score
                result_data['vector_score'] = scores['vector_score']
                result_data['keyword_score'] = scores['keyword_score']

                scored_results.append(result_data)

            # Sort by combined score and return top_k
            scored_results.sort(key=lambda x: x['combined_score'], reverse=True)

            logger.info(f"Hybrid search found {len(scored_results)} results")
            return scored_results[:top_k]

        except Exception as e:
            logger.error(f"Error in hybrid search: {e}")
            return []

    async def keyword_search(
        self,
        query_text: str,
        top_k: int = 5,
        case_sensitive: bool = False
    ) -> List[Dict[str, Any]]:
        """Keyword/BM25-like search by matching query terms in content"""
        try:
            collection = await self._get_collection()

            # Get all entities (for keyword matching)
            # In production, you might want to use a text index or external search
            results = collection.query(
                expr="",
                output_fields=["id", "content", "metadata_str"],
                limit=1000
            )

            # Score based on keyword matching
            scored_results = []
            query_terms = query_text.lower().split() if not case_sensitive else query_text.split()

            import json
            for entity in results:
                content = entity.get("content", "").lower() if not case_sensitive else entity.get("content", "")

                # Calculate relevance score based on term frequency
                score = 0.0
                term_count = 0

                for term in query_terms:
                    if term in content:
                        # Count occurrences
                        count = content.count(term)
                        score += count

                        # Boost if term appears at the beginning
                        if content.startswith(term):
                            score += 5

                        term_count += 1

                # Normalize score by content length
                if len(content) > 0:
                    score = score / len(content)

                # Add bonus for matching more terms
                match_ratio = term_count / len(query_terms) if query_terms else 0
                score = score * (1 + match_ratio)

                if score > 0:
                    try:
                        metadata = json.loads(entity.get("metadata_str", "{}"))
                    except:
                        metadata = {}

                    result = {
                        'id': entity.get("id"),
                        'content': content,
                        'score': score,
                        'matched_terms': term_count,
                        'total_terms': len(query_terms),
                        'metadata': metadata
                    }
                    scored_results.append(result)

            # Sort by score and return top_k
            scored_results.sort(key=lambda x: x['score'], reverse=True)

            logger.info(f"Keyword search found {len(scored_results)} results")
            return scored_results[:top_k]

        except Exception as e:
            logger.error(f"Error in keyword search: {e}")
            return []

    async def drop_collection(self) -> bool:
        """Drop the collection"""
        try:
            await self._get_connection()

            if utility.has_collection(self.collection_name):
                utility.drop_collection(self.collection_name)
                self._collection = None
                logger.info(f"Dropped collection: {self.collection_name}")
                return True
            else:
                logger.warning(f"Collection {self.collection_name} does not exist")
                return False

        except Exception as e:
            logger.error(f"Failed to drop collection: {str(e)}")
            return False

    async def get_collection_stats(self) -> Dict[str, Any]:
        """Get collection statistics"""
        try:
            collection = await self._get_collection()

            stats = {
                "num_entities": collection.num_entities,
                "collection_name": self.collection_name,
                "vector_dimension": self.vector_dimension,
                "initialized": self._initialized
            }

            return stats

        except Exception as e:
            logger.error(f"Failed to get collection stats: {str(e)}")
            return {}
