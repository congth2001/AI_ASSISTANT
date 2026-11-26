import logging
from openai import OpenAI
from typing import List
from src.modules.assistant.domain.ports.i_embedding_service import IEmbeddingService
from src.modules.assistant.domain.errors import (
    BatchEmbeddingRequestError,
    EmbeddingRequestError,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 2


class OpenAIEmbedding(IEmbeddingService):
    """OpenAI implementation of embedding service.

    Client là đồng bộ (blocking I/O): caller async phải gọi qua ``asyncio.to_thread``.
    ``timeout`` (giây) và ``max_retries`` giới hạn thời gian chặn một lần gọi.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        vector_dimension: int = 1024,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.api_key = api_key
        self.model = model
        self.vector_dimension = vector_dimension
        self.timeout = timeout
        self.max_retries = max_retries
        # use new OpenAI client for openai>=1.0.0
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)

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
            logger.error("OpenAI embedding request failed (model=%s): %s", self.model, e)
            raise EmbeddingRequestError() from e

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
            logger.error(
                "OpenAI batch embedding request failed (model=%s, texts=%d): %s",
                self.model, len(texts), e,
            )
            raise BatchEmbeddingRequestError() from e
