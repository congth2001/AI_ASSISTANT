# Hybrid Search Implementation

## Overview

The Business Chatbot now supports **Hybrid Search** - combining semantic vector search with keyword/BM25-like matching. This provides better retrieval quality by leveraging both semantic understanding and exact keyword matching.

## Architecture

### Three Search Methods

#### 1. **Vector Search (Semantic)**
- Finds semantically similar content
- Uses embeddings and L2 distance
- Good for conceptual queries
- Fast with vector indexing

```python
results = await vector_db.search_similar(query_embedding, top_k=5)
```

#### 2. **Keyword Search (BM25-like)**
- Finds exact keyword matches
- Calculates relevance based on term frequency
- Good for specific terms and phrases
- Implements term frequency and position boosting

```python
results = await vector_db.keyword_search("query text", top_k=5)
```

#### 3. **Hybrid Search (RECOMMENDED)**
- Combines both vector and keyword search
- Configurable weights for fine-tuning
- Best of both worlds
- Production-recommended approach

```python
results = await vector_db.hybrid_search(
    query_vector=embedding,
    query_text="query text",
    vector_weight=0.7,
    keyword_weight=0.3
)
```

## Implementation Details

### Collection Schema

The Milvus collection has been updated to support hybrid search:

```
Field: id (VARCHAR, primary key)
Field: vector (FLOAT_VECTOR, 512 dims)
Field: content (VARCHAR, 8192 chars) ← NEW for keyword search
Field: metadata_str (VARCHAR, 4096 chars)
```

### Scoring Algorithm

#### Vector Score
```
vector_similarity = 1.0 / (1.0 + l2_distance)
```

#### Keyword Score (BM25-like)
```
for each query term:
  - Count term occurrences in content
  - Boost if term appears at beginning
  - Normalize by content length
  - Add match ratio bonus

score = (occurrence_count / content_length) * (1 + match_ratio)
```

#### Combined Score
```
combined_score = vector_weight * vector_score + keyword_weight * keyword_score
```

### Default Configuration

- **Vector Weight**: 0.7 (70%)
- **Keyword Weight**: 0.3 (30%)

This means semantic understanding is prioritized, but keyword matching is still important.

## Usage Examples

### Basic Hybrid Search

```python
from config.container import container
from config.settings import settings

# Setup
container.config.from_dict(settings.dict())
vector_db = container.vector_db()
embedding_service = container.embedding_service()

# Get embedding
query = "monthly sales revenue"
query_embedding = await embedding_service.generate_embedding(query)

# Hybrid search
results = await vector_db.hybrid_search(
    query_vector=query_embedding,
    query_text=query,
    top_k=5,
    vector_weight=0.7,
    keyword_weight=0.3
)

# Results include:
# - id: document ID
# - combined_score: weighted score (0-1)
# - vector_score: semantic similarity score
# - keyword_score: keyword matching score
# - content: document content
# - metadata: associated metadata
```

### RAG with Hybrid Retrieval

```python
rag_orchestrator = container.rag_orchestrator()

result = await rag_orchestrator.hybrid_retrieve_and_generate(
    query="What was our Q4 profit?",
    top_k=5,
    vector_weight=0.7,
    keyword_weight=0.3
)

# Returns:
# - response: LLM-generated answer
# - retrieved_context: concatenated search results
# - search_scores: detailed scoring breakdown
# - retrieval_method: 'hybrid'
```

### Compare Different Approaches

```python
# Vector-only (semantic)
vector_results = await vector_db.search_similar(embedding, top_k=5)

# Keyword-only (exact match)
keyword_results = await vector_db.keyword_search("query", top_k=5)

# Hybrid (best of both)
hybrid_results = await vector_db.hybrid_search(embedding, "query", top_k=5)
```

## Weight Tuning Guide

### Use Cases and Recommended Weights

#### Balanced (Default)
```python
vector_weight=0.7, keyword_weight=0.3
# Best for: General business queries
# Reason: Semantic search catches related concepts, keywords ensure exact matches
```

#### Semantic Heavy
```python
vector_weight=0.9, keyword_weight=0.1
# Best for: Conceptual analysis, trend analysis
# Reason: Prioritize semantic understanding of business concepts
```

#### Keyword Heavy
```python
vector_weight=0.3, keyword_weight=0.7
# Best for: Financial reports, product names, specific metrics
# Reason: Exact terms are critical for accuracy
```

#### Pure Vector
```python
vector_weight=1.0, keyword_weight=0.0
# Use when: Only semantic search is needed
# Reason: Fast, simple, good for semantic understanding only
```

#### Pure Keyword
```python
vector_weight=0.0, keyword_weight=1.0
# Use when: Only exact matching is needed
# Reason: Good for database lookups, product searches
```

## Performance Considerations

### Vector Search
- **Speed**: Very Fast (indexed)
- **Accuracy**: Good (captures semantics)
- **Memory**: Moderate (index storage)

### Keyword Search
- **Speed**: Moderate (scans documents)
- **Accuracy**: Good (exact matching)
- **Memory**: Low

### Hybrid Search
- **Speed**: Moderate (vector fast + keyword moderate)
- **Accuracy**: Excellent (combines both)
- **Memory**: Moderate

### Optimization Tips

1. **Top-K Parameter**
   ```python
   # Increase for more thorough search (slower)
   top_k=10
   # Decrease for speed (may miss results)
   top_k=3
   ```

2. **Re-ranking with Hybrid**
   ```python
   # Hybrid search naturally re-ranks results
   # Top results often better than pure vector or keyword
   ```

3. **Caching**
   ```python
   # Consider caching frequent queries
   # Hybrid search scores are deterministic
   ```

## API Reference

### `hybrid_search()`
```python
async def hybrid_search(
    query_vector: List[float],
    query_text: str,
    top_k: int = 5,
    vector_weight: float = 0.7,
    keyword_weight: float = 0.3
) -> List[Dict[str, Any]]
```

**Parameters:**
- `query_vector`: Embedding vector for semantic search
- `query_text`: Text for keyword search
- `top_k`: Number of results to return (default: 5)
- `vector_weight`: Weight for vector similarity (0-1, default: 0.7)
- `keyword_weight`: Weight for keyword matching (0-1, default: 0.3)

**Returns:**
```python
[
    {
        'id': 'doc_1',
        'combined_score': 0.85,
        'vector_score': 0.9,
        'keyword_score': 0.7,
        'content': 'document content...',
        'metadata': {...}
    },
    ...
]
```

### `keyword_search()`
```python
async def keyword_search(
    query_text: str,
    top_k: int = 5,
    case_sensitive: bool = False
) -> List[Dict[str, Any]]
```

**Parameters:**
- `query_text`: Query text for keyword matching
- `top_k`: Number of results
- `case_sensitive`: Whether to match case (default: False)

## Troubleshooting

### Low Scores in Keyword Search
- **Cause**: Query terms don't match document content
- **Solution**: 
  - Use broader terms
  - Lower keyword_weight in hybrid search
  - Check content field is populated

### Semantic Mismatches
- **Cause**: Embedding model doesn't capture your domain
- **Solution**:
  - Increase vector_weight
  - Fine-tune embedding model for domain
  - Add domain-specific terms to content

### Performance Issues
- **Cause**: Scanning too many documents
- **Solution**:
  - Reduce top_k parameter
  - Implement document filtering first
  - Use vector search (indexed) primarily

## Future Improvements

1. **Elasticsearch Integration** - For large-scale keyword search
2. **BM25 Index** - True BM25 algorithm in Milvus
3. **Domain-Specific Embeddings** - Fine-tuned models for business terms
4. **Query Expansion** - Automatically expand queries with synonyms
5. **Learning-to-Rank** - ML model to optimize weights per query type

## Examples

See `examples/hybrid_search_example.py` for complete runnable examples including:
- Vector-only search
- Keyword search
- Hybrid search
- RAG with hybrid retrieval
- Weight tuning demonstrations
