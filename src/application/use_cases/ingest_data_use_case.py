from typing import Optional, Dict, Any, List
from src.domain.interfaces.i_data_repository import IDataRepository
from src.domain.interfaces.i_vector_db import IVectorDB
from src.domain.interfaces.i_embedding_service import IEmbeddingService
from src.domain.entities.business_data import BusinessData
from src.domain.value_objects.date_range import DateRange
from decimal import Decimal
import json


class IngestDataUseCase:
    """Use case for ingesting business data into the system"""

    def __init__(
        self,
        data_repo: IDataRepository,
        vector_db: IVectorDB,
        embedding_service: IEmbeddingService
    ):
        self.data_repo = data_repo
        self.vector_db = vector_db
        self.embedding_service = embedding_service

    async def execute(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute data ingestion"""
        # Validate data
        self._validate_data(data)

        # Store in data repository
        stored = await self.data_repo.store_business_data(data)

        if not stored:
            raise Exception("Failed to store business data")

        # Generate embedding for vector search
        data_text = self._data_to_text(data)
        embedding = await self.embedding_service.generate_embedding(data_text)

        # Store embedding in vector database
        vector_id = f"{data['data_type']}_{data['id']}"
        metadata = {
            'data_type': data['data_type'],
            'date': data.get('date'),
            'category': data.get('category'),
            'source': 'ingestion'
        }

        vector_stored = await self.vector_db.store_embedding(vector_id, embedding, metadata)

        return {
            'success': True,
            'data_id': data['id'],
            'vector_stored': vector_stored,
            'embedding_dimension': len(embedding)
        }

    def _validate_data(self, data: Dict[str, Any]):
        """Validate business data structure"""
        required_fields = ['id', 'data_type', 'value']
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")

        # Validate data types
        if not isinstance(data['value'], (int, float, str)):
            raise ValueError("Value must be numeric or string")

        # Convert string numbers to float
        if isinstance(data['value'], str):
            try:
                data['value'] = float(data['value'])
            except ValueError:
                raise ValueError("String value must be numeric")

    def _data_to_text(self, data: Dict[str, Any]) -> str:
        """Convert data to text for embedding"""
        text_parts = [
            f"Data type: {data['data_type']}",
            f"Value: {data['value']}",
            f"Date: {data.get('date', 'N/A')}",
        ]

        if data.get('category'):
            text_parts.append(f"Category: {data['category']}")

        if data.get('subcategory'):
            text_parts.append(f"Subcategory: {data['subcategory']}")

        if data.get('metadata'):
            text_parts.append(f"Metadata: {json.dumps(data['metadata'])}")

        return ". ".join(text_parts)