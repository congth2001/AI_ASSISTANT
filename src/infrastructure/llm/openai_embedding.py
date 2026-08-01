from openai import OpenAI
from typing import List
from src.domain.interfaces.i_embedding_service import IEmbeddingService


class OpenAIEmbedding(IEmbeddingService):
    """OpenAI implementation of embedding service"""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", vector_dimension: int = 1024):
        self.api_key = api_key
        self.model = model
        self.vector_dimension = vector_dimension
        # use new OpenAI client for openai>=1.0.0
        self.client = OpenAI(api_key=api_key)

    def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for text"""
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text,
                dimensions=self.vector_dimension,
            )

            embedding = response.data[0].embedding
            return embedding

        except Exception as e:
            raise Exception(f"OpenAI embedding error: {str(e)}")

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=texts,
                dimensions=self.vector_dimension,
            )

            embeddings = [d.embedding for d in response.data]
            return embeddings

        except Exception as e:
            raise Exception(f"OpenAI batch embedding error: {str(e)}")