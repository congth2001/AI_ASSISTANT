import openai
from typing import List
from src.domain.interfaces.i_embedding_service import IEmbeddingService


class OpenAIEmbeddingService(IEmbeddingService):
    """OpenAI implementation of embedding service"""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.api_key = api_key
        self.model = model
        openai.api_key = api_key

    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for text"""
        try:
            response = await openai.Embedding.acreate(
                input=text,
                model=self.model
            )

            embedding = response['data'][0]['embedding']
            return embedding

        except Exception as e:
            raise Exception(f"OpenAI embedding error: {str(e)}")

    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        try:
            response = await openai.Embedding.acreate(
                input=texts,
                model=self.model
            )

            embeddings = [data['embedding'] for data in response['data']]
            return embeddings

        except Exception as e:
            raise Exception(f"OpenAI batch embedding error: {str(e)}")