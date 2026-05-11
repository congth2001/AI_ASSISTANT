from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any
from decimal import Decimal


@dataclass
class Report:
    """Entity representing a business report"""
    id: Optional[str] = None
    title: str
    report_type: str  # 'revenue', 'profit', 'customer_analysis', 'trend', etc.
    date_range: 'DateRange'
    data: Dict[str, Any]
    insights: List[str]
    recommendations: List[str]
    generated_at: datetime = None
    metadata: Optional[dict] = None

    def __post_init__(self):
        if self.generated_at is None:
            self.generated_at = datetime.now()


@dataclass
class MetricSummary:
    """Entity representing summarized business metrics"""
    metric_type: str
    value: Decimal
    change_percentage: Optional[Decimal] = None
    period: str  # 'daily', 'weekly', 'monthly', 'yearly'
    date: datetime
    metadata: Optional[dict] = None