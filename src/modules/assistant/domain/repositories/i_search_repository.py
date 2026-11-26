from abc import ABC

from src.modules.assistant.domain.entities.analyzed_query import AnalyzedQuery
from src.modules.assistant.domain.entities.search_result import SearchResult


class ISearchRepository(ABC):
    def search(self, query: AnalyzedQuery) -> list[SearchResult]:
        raise NotImplementedError