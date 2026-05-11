from typing import List, Tuple, Optional, Dict, Any
import logging
from pymilvus import Collection, connections, utility, FieldSchema, CollectionSchema, DataType
from src.domain.entities.face_vector import FaceVector
from src.domain.entities.errors import VectorNotFoundException, StorageException
from ...domain.repositories.vector_repository import VectorRepository
from src.domain.entities.constants import FaceRecognitionConstants

logger = logging.getLogger(__name__)


class MilvusVectorRepository(VectorRepository):
    """Milvus implementation of vector repository"""
    
    def __init__(
        self, 
        host: str = "localhost", 
        port: int = 19530,
        collection_name: str = None
    ):
        self.host = host
        self.port = port
        self.collection_name = collection_name or FaceRecognitionConstants.MILVUS_COLLECTION_NAME
        self._connection = None
        self._collection = None
    
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
                raise StorageException(f"Failed to connect to Milvus: {str(e)}")
        return self._connection

    async def _get_collection(self) -> Collection:
        """Get or create collection"""
        if self._collection is None:
            try:
                await self._get_connection()
                
                # Check if collection exists
                if utility.has_collection(self.collection_name):
                    self._collection = Collection(self.collection_name)
                else:
                    # Create collection if it doesn't exist
                    await self.create_collection(
                        self.collection_name, 
                        FaceRecognitionConstants.FACENET_VECTOR_DIMENSION
                    )
                    self._collection = Collection(self.collection_name)
                
                logger.info(f"Using collection: {self.collection_name}")
            except Exception as e:
                raise StorageException(f"Failed to get collection: {str(e)}")
        return self._collection

    async def create_collection(self, collection_name: str, dimension: int) -> bool:
        """Create a new vector collection"""
        try:
            await self._get_connection()
            
            # Define collection schema
            fields = [
                FieldSchema(
                    name="id", 
                    dtype=DataType.VARCHAR, 
                    is_primary=True, 
                    max_length=100
                ),
                FieldSchema(
                    name="face_id", 
                    dtype=DataType.VARCHAR, 
                    max_length=100
                ),
                FieldSchema(
                    name="vector", 
                    dtype=DataType.FLOAT_VECTOR, 
                    dim=dimension
                ),
                FieldSchema(
                    name="model_version", 
                    dtype=DataType.VARCHAR, 
                    max_length=50
                )
            ]
            
            schema = CollectionSchema(
                fields=fields, 
                description="Face recognition vectors"
            )
            
            # Create collection
            collection = Collection(
                name=collection_name,
                schema=schema,
                using='default',
                shards_num=2
            )
            
            # Create index
            await self.create_index(collection_name)
            
            logger.info(f"Created collection: {collection_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create collection: {str(e)}")
            raise StorageException(f"Failed to create collection: {str(e)}")

    async def drop_collection(self, collection_name: str) -> bool:
        """Drop a vector collection"""
        try:
            await self._get_connection()
            
            if utility.has_collection(collection_name):
                utility.drop_collection(collection_name)
                logger.info(f"Dropped collection: {collection_name}")
                return True
            else:
                logger.warning(f"Collection {collection_name} does not exist")
                return False
                
        except Exception as e:
            logger.error(f"Failed to drop collection: {str(e)}")
            raise StorageException(f"Failed to drop collection: {str(e)}")

    async def create_index(self, collection_name: str, index_type: str = "IVF_FLAT") -> bool:
        """Create index for the collection"""
        try:
            collection = Collection(collection_name)
            
            # Create index on vector field
            index_params = {
                "metric_type": FaceRecognitionConstants.MILVUS_METRIC_TYPE,
                "index_type": index_type,
                "params": {"nlist": 1024}
            }
            
            collection.create_index(
                field_name="vector",
                index_params=index_params
            )
            
            logger.info(f"Created index for collection: {collection_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create index: {str(e)}")
            raise StorageException(f"Failed to create index: {str(e)}")

    async def insert_vector(self, vector: FaceVector) -> bool:
        """Insert a single face vector"""
        try:
            collection = await self._get_collection()
            
            # Prepare data
            data = [
                [vector.id],
                [vector.face_id],
                [vector.embedding],
                # [vector.model_version]
            ]
            
            # Insert data
            collection.insert(data)
            collection.flush()
            
            logger.info(f"Inserted vector for face: {vector.face_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to insert vector: {str(e)}")
            raise StorageException(f"Failed to insert vector: {str(e)}")

    async def insert_vectors(self, vectors: List[FaceVector]) -> bool:
        """Insert multiple face vectors"""
        try:
            if not vectors:
                return True
                
            collection = await self._get_collection()
            
            # Prepare data
            ids = [v.id for v in vectors]
            face_ids = [v.face_id for v in vectors]
            vector_data = [v.embedding for v in vectors]
            # model_versions = [v.model_version for v in vectors]
            
            # data = [ids, face_ids, vector_data, model_versions]
            data = [ids, face_ids, vector_data]
            
            # Insert data
            collection.insert(data)
            collection.flush()
            
            logger.info(f"Inserted {len(vectors)} vectors")
            return True
            
        except Exception as e:
            logger.error(f"Failed to insert vectors: {str(e)}")
            raise StorageException(f"Failed to insert vectors: {str(e)}")

    async def get_vector(self, face_id: str) -> Optional[FaceVector]:
        """Get vector by face ID"""
        try:
            collection = await self._get_collection()
            
            # Load collection
            collection.load()
            
            # Search for the specific face_id
            search_params = {
                "metric_type": FaceRecognitionConstants.MILVUS_METRIC_TYPE,
                "params": {"nprobe": 10}
            }
            
            # Create a dummy query vector (we'll filter by face_id)
            dummy_vector = [0.0] * FaceRecognitionConstants.FACENET_VECTOR_DIMENSION
            
            results = collection.search(
                data=[dummy_vector],
                anns_field="vector",
                param=search_params,
                limit=1,
                expr=f'face_id == "{face_id}"',
                output_fields=["face_id", "vector", "model_version"]
            )
            
            if results and len(results[0]) > 0:
                result = results[0][0]
                return FaceVector(
                    id=result.id,
                    face_id=result.entity.get("face_id"),
                    vector=result.entity.get("vector"),
                    model_version=result.entity.get("model_version")
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get vector: {str(e)}")
            raise StorageException(f"Failed to get vector: {str(e)}")

    async def search_similar(
        self, 
        query_vector: List[float], 
        top_k: int = 10,
        threshold: float = 0.6
    ) -> List[Tuple[str, float]]:
        """Search for similar vectors"""
        try:
            collection = await self._get_collection()
            
            # Load collection
            collection.load()
            
            # Search parameters
            search_params = {
                "metric_type": FaceRecognitionConstants.MILVUS_METRIC_TYPE,
                "params": {"nprobe": 10}
            }
            
            # Perform search
            results = collection.search(
                data=[query_vector],
                anns_field="vector",
                param=search_params,
                limit=top_k,
                output_fields=["face_id"]
            )
            
            # Process results
            matches = []
            if results and len(results[0]) > 0:
                for hit in results[0]:
                    face_id = hit.entity.get("face_id")
                    distance = hit.distance
                    
                    # Convert distance to similarity (for L2 distance)
                    similarity = 1.0 / (1.0 + distance)
                    
                    if similarity >= threshold:
                        matches.append((face_id, similarity))
            
            return matches
            
        except Exception as e:
            logger.error(f"Failed to search similar vectors: {str(e)}")
            raise StorageException(f"Failed to search similar vectors: {str(e)}")

    async def delete_vector(self, face_id: str) -> bool:
        """Delete vector by face ID"""
        try:
            collection = await self._get_collection()
            
            # Delete by face_id
            collection.delete(expr=f'face_id == "{face_id}"')
            collection.flush()
            
            logger.info(f"Deleted vector for face: {face_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete vector: {str(e)}")
            raise StorageException(f"Failed to delete vector: {str(e)}")

    async def delete_vectors(self, face_ids: List[str]) -> bool:
        """Delete multiple vectors by face IDs"""
        try:
            if not face_ids:
                return True
                
            collection = await self._get_collection()
            
            # Create expression for multiple face_ids
            face_id_list = '", "'.join(face_ids)
            expr = f'face_id in ["{face_id_list}"]'
            
            # Delete vectors
            collection.delete(expr=expr)
            collection.flush()
            
            logger.info(f"Deleted {len(face_ids)} vectors")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete vectors: {str(e)}")
            raise StorageException(f"Failed to delete vectors: {str(e)}")

    async def get_collection_stats(self, collection_name: str) -> dict:
        """Get collection statistics"""
        try:
            collection = Collection(collection_name)
            
            stats = {
                "num_entities": collection.num_entities,
                "collection_name": collection_name,
                "schema": collection.schema
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get collection stats: {str(e)}")
            raise StorageException(f"Failed to get collection stats: {str(e)}")
