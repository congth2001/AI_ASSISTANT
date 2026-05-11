#!/usr/bin/env python3
"""
Hybrid Search Example for Business Chatbot
Demonstrates both vector-only and hybrid (vector + keyword) search
"""
import asyncio
from config.settings import settings
from config.container import container


async def example_vector_search():
    """Example: Pure vector similarity search"""
    print("=" * 60)
    print("EXAMPLE 1: Pure Vector Search (Semantic)")
    print("=" * 60)

    # Configure container
    container.config.from_dict(settings.dict())
    container.database_url.override(settings.database.url)

    # Get vector DB
    vector_db = container.vector_db()

    # Sample query embedding (normally comes from embedding service)
    query_embedding = [0.1] * 512  # Dummy 512-dim vector

    # Vector search
    results = await vector_db.search_similar(query_embedding, top_k=5)

    print(f"\nFound {len(results)} results:")
    for i, result in enumerate(results, 1):
        print(f"\n  {i}. ID: {result['id']}")
        print(f"     Vector Score: {result['score']:.4f}")
        print(f"     Content: {result['content'][:100]}...")


async def example_keyword_search():
    """Example: Keyword/BM25-like search"""
    print("\n" + "=" * 60)
    print("EXAMPLE 2: Keyword Search (BM25-like)")
    print("=" * 60)

    # Configure container
    container.config.from_dict(settings.dict())
    container.database_url.override(settings.database.url)

    # Get vector DB
    vector_db = container.vector_db()

    # Keyword search
    query_text = "revenue sales profit"
    results = await vector_db.keyword_search(query_text, top_k=5)

    print(f"\nKeyword query: '{query_text}'")
    print(f"Found {len(results)} results:")
    for i, result in enumerate(results, 1):
        print(f"\n  {i}. ID: {result['id']}")
        print(f"     Keyword Score: {result['score']:.4f}")
        print(f"     Matched Terms: {result['matched_terms']}/{result['total_terms']}")
        print(f"     Content: {result['content'][:100]}...")


async def example_hybrid_search():
    """Example: Hybrid search combining vector + keyword"""
    print("\n" + "=" * 60)
    print("EXAMPLE 3: Hybrid Search (Vector + Keyword)")
    print("=" * 60)

    # Configure container
    container.config.from_dict(settings.dict())
    container.database_url.override(settings.database.url)

    # Get services
    vector_db = container.vector_db()
    embedding_service = container.embedding_service()

    # Get embedding for query
    query_text = "monthly revenue analysis"
    query_embedding = await embedding_service.generate_embedding(query_text)

    # Hybrid search
    results = await vector_db.hybrid_search(
        query_vector=query_embedding,
        query_text=query_text,
        top_k=5,
        vector_weight=0.7,  # 70% weight to vector similarity
        keyword_weight=0.3  # 30% weight to keyword matching
    )

    print(f"\nHybrid query: '{query_text}'")
    print(f"Vector weight: 70%, Keyword weight: 30%")
    print(f"Found {len(results)} results:")
    for i, result in enumerate(results, 1):
        print(f"\n  {i}. ID: {result['id']}")
        print(f"     Combined Score: {result['combined_score']:.4f}")
        print(f"     Vector Score:  {result['vector_score']:.4f}")
        print(f"     Keyword Score: {result['keyword_score']:.4f}")
        print(f"     Content: {result['content'][:100]}...")


async def example_rag_with_hybrid():
    """Example: RAG with hybrid retrieval"""
    print("\n" + "=" * 60)
    print("EXAMPLE 4: RAG with Hybrid Retrieval")
    print("=" * 60)

    # Configure container
    container.config.from_dict(settings.dict())
    container.database_url.override(settings.database.url)

    # Get RAG orchestrator
    rag_orchestrator = container.rag_orchestrator()

    # Query
    query = "What was our total profit last quarter?"

    # Hybrid RAG retrieval and generation
    result = await rag_orchestrator.hybrid_retrieve_and_generate(
        query=query,
        top_k=5,
        vector_weight=0.7,
        keyword_weight=0.3
    )

    print(f"\nQuery: '{query}'")
    print(f"Retrieval Method: {result['retrieval_method']}")
    print(f"Results Count: {result['search_results_count']}")
    print(f"Context Sources: {result['context_sources']}")
    print(f"\nGenerated Response:\n{result['response']}")
    print(f"\nRetrieved Context:\n{result['retrieved_context'][:200]}...")

    if result.get('search_scores'):
        print(f"\nSearch Scores:")
        for score in result['search_scores'][:3]:
            print(f"  - {score['id']}: combined={score['combined_score']:.4f}, "
                  f"vector={score['vector_score']:.4f}, keyword={score['keyword_score']:.4f}")


async def example_config_tuning():
    """Example: Tuning hybrid search weights"""
    print("\n" + "=" * 60)
    print("EXAMPLE 5: Tuning Hybrid Search Weights")
    print("=" * 60)

    # Configure container
    container.config.from_dict(settings.dict())
    container.database_url.override(settings.database.url)

    # Get RAG orchestrator
    rag_orchestrator = container.rag_orchestrator()

    query = "customer retention rate"

    print(f"\nQuery: '{query}'")
    print(f"\nTesting different weight combinations:\n")

    # Test different weight combinations
    weight_configs = [
        (1.0, 0.0, "Pure Vector Search"),
        (0.8, 0.2, "Vector Heavy (80/20)"),
        (0.7, 0.3, "Balanced (70/30) - Recommended"),
        (0.5, 0.5, "Equal Weight (50/50)"),
        (0.3, 0.7, "Keyword Heavy (30/70)"),
        (0.0, 1.0, "Pure Keyword Search"),
    ]

    for vector_weight, keyword_weight, description in weight_configs:
        print(f"{description}:")
        print(f"  Vector: {vector_weight}, Keyword: {keyword_weight}")

        result = await rag_orchestrator.hybrid_retrieve_and_generate(
            query=query,
            top_k=3,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight
        )

        if result.get('search_scores'):
            top_score = result['search_scores'][0]
            print(f"  Top result combined score: {top_score['combined_score']:.4f}\n")


async def main():
    """Run all examples"""
    print("\n" + "=" * 60)
    print("HYBRID SEARCH EXAMPLES FOR BUSINESS CHATBOT")
    print("=" * 60)

    try:
        # Run examples
        await example_vector_search()
        await example_keyword_search()
        await example_hybrid_search()
        await example_rag_with_hybrid()
        await example_config_tuning()

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print("""
Vector-Only Search:
  - Fast semantic search
  - Good for finding conceptually similar content
  - May miss exact keyword matches

Keyword Search:
  - Exact phrase matching
  - Good for finding specific terms
  - May miss conceptually similar content

Hybrid Search (RECOMMENDED):
  - Combines semantic understanding + exact matching
  - Best of both worlds
  - Tunable weights for different use cases
  - Recommended for production business chatbots

Best Practices:
  1. Use 70/30 (vector/keyword) as default
  2. Adjust weights based on use case:
     - More vector weight for conceptual queries
     - More keyword weight for precise terms
  3. Monitor retrieval quality and user feedback
  4. Consider implementing feedback loop for tuning
        """)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
