from typing import Dict, Optional
from src.infrastructure.utils.singleton import Singleton

# Try to import MongoDB dependencies, fallback to mock if not available
try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from motor.core import Collection
    from bson import ObjectId
    from pymongo.results import (
        InsertOneResult,
        InsertManyResult,
        UpdateResult,
        DeleteResult,
    )
    from fastapi.encoders import jsonable_encoder
    MONGO_AVAILABLE = True
except ImportError:
    # Mock classes for when dependencies are not available
    class AsyncIOMotorClient:
        def __init__(self, *args, **kwargs):
            pass
        def close(self):
            pass
    
    class Collection:
        pass
    
    class ObjectId:
        pass
    
    class InsertOneResult:
        pass
    
    class InsertManyResult:
        pass
    
    class UpdateResult:
        pass
    
    class DeleteResult:
        pass
    
    def jsonable_encoder(obj, **kwargs):
        return obj
    
    MONGO_AVAILABLE = False


def encode_update(document):
    return jsonable_encoder(document, exclude_unset=True, exclude_none=True)


def encode_insert(document):
    document = jsonable_encoder(document, exclude_none=True)
    return document


class MongoConnection(metaclass=Singleton):
    """MongoDB connection manager"""
    
    def __init__(self):
        self._client: Optional[AsyncIOMotorClient] = None
        self._db = None

    def init_app(self, config: Dict):
        """Initialize MongoDB connection with config"""
        self._client = AsyncIOMotorClient(config['mongodb']['url'])
        self._db = self._client[config['mongodb']['database']]

    @property
    def client(self) -> AsyncIOMotorClient:
        """Get MongoDB client"""
        if self._client is None:
            raise RuntimeError("MongoDB connection not initialized. Call init_app() first.")
        return self._client

    @property
    def db(self):
        """Get MongoDB database"""
        if self._db is None:
            raise RuntimeError("MongoDB connection not initialized. Call init_app() first.")
        return self._db

    def get_collection(self, collection_name: str) -> Collection:
        """Get a specific collection"""
        return self.db[collection_name]

    async def close(self):
        """Close MongoDB connection"""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None


# Global instance
mongo_connection = MongoConnection()
