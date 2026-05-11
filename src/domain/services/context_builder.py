from typing import List, Dict, Any, Optional
from src.domain.entities.message import Message
from src.domain.value_objects.query_intent import QueryIntent


class ContextBuilder:
    """Domain service for building conversation context"""

    def __init__(self, max_context_messages: int = 10):
        self.max_context_messages = max_context_messages

    def build_context(self, messages: List[Message], current_query: str) -> Dict[str, Any]:
        """Build context from conversation history"""
        # Get recent messages for context
        recent_messages = messages[-self.max_context_messages:] if len(messages) > self.max_context_messages else messages

        # Format conversation history
        conversation_history = []
        for msg in recent_messages:
            conversation_history.append({
                'role': msg.role,
                'content': msg.content,
                'timestamp': msg.timestamp.isoformat() if msg.timestamp else None
            })

        # Extract key information from current query
        context = {
            'conversation_history': conversation_history,
            'current_query': current_query,
            'total_messages': len(messages),
            'context_window': len(recent_messages)
        }

        return context

    def extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text for better context"""
        # Simple keyword extraction (can be enhanced with NLP)
        words = text.lower().split()
        # Remove common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        keywords = [word for word in words if word not in stop_words and len(word) > 2]
        return list(set(keywords))  # Remove duplicates

    def summarize_conversation(self, messages: List[Message]) -> str:
        """Create a summary of the conversation"""
        if not messages:
            return "No previous conversation"

        # Simple summary based on message count and recent topics
        total_messages = len(messages)
        user_messages = [msg for msg in messages if msg.role == 'user']

        if total_messages == 0:
            return "Empty conversation"

        # Extract topics from recent user messages
        recent_user_messages = user_messages[-3:]  # Last 3 user messages
        topics = []
        for msg in recent_user_messages:
            keywords = self.extract_keywords(msg.content)
            topics.extend(keywords[:2])  # Take first 2 keywords from each message

        unique_topics = list(set(topics))[:5]  # Limit to 5 unique topics

        summary = f"Conversation with {total_messages} messages"
        if unique_topics:
            summary += f" about {', '.join(unique_topics)}"

        return summary