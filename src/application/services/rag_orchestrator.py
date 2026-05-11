from typing import Optional, Dict, Any, List
from src.domain.interfaces.i_vector_db import IVectorDB
from src.domain.interfaces.i_embedding_service import IEmbeddingService
from src.domain.interfaces.i_llm_service import ILLMService
from src.domain.services.context_builder import ContextBuilder


class RAGOrchestrator:
    """Application service for Retrieval-Augmented Generation"""

    def __init__(
        self,
        vector_db: IVectorDB,
        embedding_service: IEmbeddingService,
        llm_service: ILLMService,
        context_builder: ContextBuilder
    ):
        self.vector_db = vector_db
        self.embedding_service = embedding_service
        self.llm_service = llm_service
        self.context_builder = context_builder

    async def retrieve_and_generate(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """Retrieve relevant information and generate response"""
        # Generate embedding for the query
        query_embedding = await self.embedding_service.generate_embedding(query)

        # Search for similar content in vector database
        similar_results = await self.vector_db.search_similar(query_embedding, top_k=top_k)

        # Extract relevant context from search results
        context_parts = []
        metadata_list = []

        for result in similar_results:
            content = result.get('metadata', {}).get('content', '')
            if content:
                context_parts.append(content)
            metadata_list.append(result.get('metadata', {}))

        # Combine context
        combined_context = "\n\n".join(context_parts)

        # Build enhanced context for LLM
        enhanced_context = {
            'retrieved_context': combined_context,
            'search_results': metadata_list,
            'query': query,
            'top_k': top_k,
            'retrieval_method': 'vector'
        }

        # Generate response using LLM with retrieved context
        response = await self.llm_service.generate_response(query, enhanced_context)

        return {
            'response': response,
            'retrieved_context': combined_context,
            'search_results_count': len(similar_results),
            'context_sources': len(context_parts),
            'retrieval_method': 'vector'
        }

    async def hybrid_retrieve_and_generate(
        self,
        query: str,
        top_k: int = 5,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3
    ) -> Dict[str, Any]:
        """Hybrid retrieval combining vector and keyword search, then generate response"""
        # Generate embedding for the query
        query_embedding = await self.embedding_service.generate_embedding(query)

        # Perform hybrid search (vector + keyword)
        hybrid_results = await self.vector_db.hybrid_search(
            query_vector=query_embedding,
            query_text=query,
            top_k=top_k,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight
        )

        # Extract relevant context from search results
        context_parts = []
        metadata_list = []
        search_scores = []

        for result in hybrid_results:
            # Get content from result
            content = result.get('content', '')
            if not content:
                content = result.get('metadata', {}).get('content', '')

            if content:
                context_parts.append(content)

            metadata_list.append(result.get('metadata', {}))
            search_scores.append({
                'id': result.get('id'),
                'combined_score': result.get('combined_score', 0),
                'vector_score': result.get('vector_score', 0),
                'keyword_score': result.get('keyword_score', 0)
            })

        # Combine context
        combined_context = "\n\n".join(context_parts)

        # Build enhanced context for LLM
        enhanced_context = {
            'retrieved_context': combined_context,
            'search_results': metadata_list,
            'search_scores': search_scores,
            'query': query,
            'top_k': top_k,
            'vector_weight': vector_weight,
            'keyword_weight': keyword_weight,
            'retrieval_method': 'hybrid'
        }

        # Generate response using LLM with retrieved context
        response = await self.llm_service.generate_response(query, enhanced_context)

        return {
            'response': response,
            'retrieved_context': combined_context,
            'search_results_count': len(hybrid_results),
            'context_sources': len(context_parts),
            'retrieval_method': 'hybrid',
            'search_scores': search_scores
        }


class QueryAnalyzer:
    """Application service for analyzing and processing queries"""

    def __init__(self, context_builder: ContextBuilder):
        self.context_builder = context_builder

    def analyze_query(self, query: str, conversation_history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Analyze user query for intent and context"""
        # Extract keywords
        keywords = self.context_builder.extract_keywords(query)

        # Determine query complexity
        complexity = self._assess_complexity(query, keywords)

        # Extract entities and concepts
        entities = self._extract_entities(query)

        # Determine response strategy
        strategy = self._determine_strategy(query, complexity, entities)

        return {
            'keywords': keywords,
            'complexity': complexity,
            'entities': entities,
            'strategy': strategy,
            'requires_data_lookup': self._requires_data_lookup(query),
            'requires_calculation': self._requires_calculation(query)
        }

    def _assess_complexity(self, query: str, keywords: List[str]) -> str:
        """Assess query complexity"""
        word_count = len(query.split())
        keyword_count = len(keywords)

        if word_count > 20 or keyword_count > 8:
            return 'complex'
        elif word_count > 10 or keyword_count > 5:
            return 'medium'
        else:
            return 'simple'

    def _extract_entities(self, query: str) -> List[str]:
        """Extract entities from query (dates, numbers, business terms)"""
        entities = []

        # Simple entity extraction (can be enhanced with NLP)
        words = query.lower().split()

        # Business entities
        business_terms = ['revenue', 'profit', 'customer', 'sales', 'inventory', 'product', 'service']
        entities.extend([word for word in words if word in business_terms])

        # Numbers
        for word in words:
            if word.isdigit():
                entities.append(f"number:{word}")

        # Date-related terms
        date_terms = ['today', 'yesterday', 'week', 'month', 'year', 'quarter']
        entities.extend([word for word in words if word in date_terms])

        return list(set(entities))  # Remove duplicates

    def _determine_strategy(self, query: str, complexity: str, entities: List[str]) -> str:
        """Determine response strategy"""
        query_lower = query.lower()

        if complexity == 'simple':
            return 'direct_answer'
        elif 'compare' in query_lower or 'vs' in query_lower:
            return 'comparison_analysis'
        elif 'trend' in query_lower or 'change' in query_lower:
            return 'trend_analysis'
        elif 'report' in query_lower or 'summary' in query_lower:
            return 'report_generation'
        elif entities:
            return 'data_driven_response'
        else:
            return 'conversational_response'

    def _requires_data_lookup(self, query: str) -> bool:
        """Check if query requires data lookup"""
        data_keywords = ['revenue', 'profit', 'sales', 'customer', 'inventory', 'data', 'report', 'analysis']
        return any(keyword in query.lower() for keyword in data_keywords)

    def _requires_calculation(self, query: str) -> bool:
        """Check if query requires calculations"""
        calc_keywords = ['calculate', 'compute', 'sum', 'average', 'total', 'percentage', 'growth', 'change']
        return any(keyword in query.lower() for keyword in calc_keywords)