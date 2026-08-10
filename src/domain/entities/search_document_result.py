from dataclasses import dataclass

from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.entities.search_result import SearchResult


@dataclass
class SearchDocumentsResult:
    results        : list[SearchResult]
    analyzed_query : AnalyzedQuery
    used_fallback  : bool
