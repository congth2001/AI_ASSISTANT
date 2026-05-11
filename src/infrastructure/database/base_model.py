from typing import Dict, Union, List
from pydantic import BaseModel, Field
from motor.core import Collection
from bson import ObjectId
from pymongo.results import (
    InsertOneResult,
    InsertManyResult,
    UpdateResult,
    DeleteResult,
)
from .mongo_connection import mongo_connection, encode_insert, encode_update


def _create_object_id():
    return str(ObjectId())


class BaseMongoModel(BaseModel):
    """Base model for MongoDB documents"""
    
    _collection = None

    id: str = Field(default_factory=_create_object_id, alias='_id')

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

    def dict_with_str_id(
            self,
            *,
            include: Union['AbstractSetIntStr', 'MappingIntStrAny'] = None,
            exclude: Union['AbstractSetIntStr', 'MappingIntStrAny'] = None,
            skip_defaults: bool = None,
            exclude_unset: bool = False,
            exclude_defaults: bool = False,
            exclude_none: bool = False) -> 'DictStrAny':
        super_dict = super().dict(
            include=include,
            exclude=exclude,
            by_alias=True,
            skip_defaults=skip_defaults,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none)
        super_dict['id'] = str(super_dict['_id'])
        return super_dict

    @classmethod
    def db(cls) -> Collection:
        """Get database collection"""
        return mongo_connection.get_collection(cls._collection)

    @classmethod
    async def find_one(cls, filter=None, *args, **kwargs):
        """Get a single document from the database"""
        obj = await cls.db().find_one(filter, *args, **kwargs)
        if obj:
            return cls.parse_obj(obj)
        return None

    @classmethod
    async def find(cls, filter=None, *args, **kwargs) -> List['BaseMongoModel']:
        """Query the database"""
        cursor = cls.db().find(filter, *args, **kwargs)
        return [cls.parse_obj(obj) async for obj in cursor]

    @classmethod
    async def insert_one(cls, document) -> InsertOneResult:
        """Insert a single document"""
        assert isinstance(document, cls)
        document = encode_insert(document)
        result = await cls.db().insert_one(document)
        return result

    @classmethod
    async def insert_many(cls, documents) -> InsertManyResult:
        """Insert multiple documents"""
        for doc in documents:
            assert isinstance(doc, cls)
        documents = (encode_insert(doc) for doc in documents)
        result = await cls.db().insert_many(documents)
        return result

    @classmethod
    async def update_one(cls, filter, update, **kwargs) -> UpdateResult:
        """Update a single document"""
        result = await cls.db().update_one(filter, update, **kwargs)
        return result

    @classmethod
    async def update_many(cls, filter, update, **kwargs) -> UpdateResult:
        """Update multiple documents"""
        result = await cls.db().update_many(filter, update, **kwargs)
        return result

    @classmethod
    async def delete_one(cls, filter, **kwargs) -> DeleteResult:
        """Delete a single document"""
        result = await cls.db().delete_one(filter, **kwargs)
        return result

    @classmethod
    async def delete_many(cls, filter, **kwargs) -> DeleteResult:
        """Delete multiple documents"""
        result = await cls.db().delete_many(filter, **kwargs)
        return result

    @classmethod
    async def count_documents(cls, filter, **kwargs) -> int:
        """Count documents matching filter"""
        result = await cls.db().count_documents(filter, **kwargs)
        return result
