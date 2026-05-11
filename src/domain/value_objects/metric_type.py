from enum import Enum
from typing import Optional


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
    AVERAGE_ORDER_VALUE = "average_order_value"
    CUSTOMER_ACQUISITION_COST = "customer_acquisition_cost"
    RETENTION_RATE = "retention_rate"