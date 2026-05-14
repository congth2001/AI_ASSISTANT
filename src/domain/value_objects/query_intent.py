from enum import Enum
from typing import Optional


class QueryIntent(Enum):
    """Enumeration of possible query intents"""
    REVENUE = "revenue"
    PROFIT = "profit"
    CUSTOMER = "customer"
    INVENTORY = "inventory"
    SALES = "sales"
    TREND = "trend"
    COMPARISON = "comparison"
    REPORT = "report"
    GENERAL = "general"
    UNKNOWN = "unknown"
