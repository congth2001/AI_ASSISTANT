from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from decimal import Decimal


@dataclass
class BusinessData:
    """Entity representing business data (revenue, customers, etc.)"""
    id: Optional[str] = None
    data_type: str  # 'revenue', 'customer', 'profit', 'inventory', etc.
    value: Decimal
    date: datetime
    category: Optional[str] = None
    subcategory: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class Customer:
    """Entity representing customer information"""
    id: Optional[str] = None
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    segment: Optional[str] = None  # 'vip', 'regular', 'new', etc.
    total_purchases: Decimal = Decimal('0')
    last_purchase_date: Optional[datetime] = None
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()


@dataclass
class Revenue:
    """Entity representing revenue data"""
    id: Optional[str] = None
    amount: Decimal
    date: datetime
    source: str  # 'sales', 'service', 'subscription', etc.
    customer_id: Optional[str] = None
    category: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class Profit:
    """Entity representing profit data"""
    id: Optional[str] = None
    revenue: Decimal
    cost: Decimal
    profit: Decimal
    date: datetime
    category: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()