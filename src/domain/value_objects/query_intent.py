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


class MetricType(Enum):
    """Enumeration of business metric types"""
    REVENUE = "revenue"
    PROFIT = "profit"
    COST = "cost"
    CUSTOMERS = "customers"
    ORDERS = "orders"
    INVENTORY = "inventory"
    GROWTH_RATE = "growth_rate"
    CONVERSION_RATE = "conversion_rate"