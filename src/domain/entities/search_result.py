from dataclasses import dataclass


@dataclass
class SearchResult:
    doc_id   : str
    doc_type : str
    text     : str
    score    : float          # cosine similarity 0–1
    metadata : dict
