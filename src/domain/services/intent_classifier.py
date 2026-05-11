from typing import Optional, Dict, Any
from src.domain.value_objects.query_intent import QueryIntent


class IntentClassifier:
    """Domain service for classifying user query intents"""

    def __init__(self):
        # Simple keyword-based classification
        self.intent_keywords = {
            QueryIntent.REVENUE: ['revenue', 'income', 'sales', 'earnings', 'money'],
            QueryIntent.PROFIT: ['profit', 'loss', 'margin', 'earnings', 'net'],
            QueryIntent.CUSTOMER: ['customer', 'client', 'buyer', 'user', 'people'],
            QueryIntent.INVENTORY: ['inventory', 'stock', 'product', 'item', 'goods'],
            QueryIntent.SALES: ['sale', 'order', 'transaction', 'purchase'],
            QueryIntent.TREND: ['trend', 'change', 'growth', 'decline', 'pattern'],
            QueryIntent.COMPARISON: ['compare', 'vs', 'versus', 'difference', 'between'],
            QueryIntent.REPORT: ['report', 'summary', 'analysis', 'overview', 'dashboard']
        }

    def classify(self, message: str) -> QueryIntent:
        """Classify the intent of a user message"""
        message_lower = message.lower()

        # Check for each intent
        for intent, keywords in self.intent_keywords.items():
            if any(keyword in message_lower for keyword in keywords):
                return intent

        return QueryIntent.GENERAL

    def get_confidence_score(self, message: str, intent: QueryIntent) -> float:
        """Get confidence score for an intent classification"""
        if intent == QueryIntent.UNKNOWN:
            return 0.0

        message_lower = message.lower()
        keywords = self.intent_keywords.get(intent, [])
        matches = sum(1 for keyword in keywords if keyword in message_lower)

        if not keywords:
            return 0.0

        return min(matches / len(keywords), 1.0)