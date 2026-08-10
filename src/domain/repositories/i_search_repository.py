from abc import ABC

from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.entities.search_result import SearchResult


class ISearchRepository(ABC):
    def search(self, query: AnalyzedQuery) -> list[SearchResult]:
        raise NotImplementedError