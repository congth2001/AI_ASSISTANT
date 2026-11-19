"""Overview-dashboard questions answered from the dashboard's own numbers."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class OverviewReportTopic(str, Enum):
    """Preset "Hỏi AI" questions of the Overview dashboard."""

    BUSINESS_OVERVIEW = "business_overview"
    DECLINING_CUSTOMERS = "declining_customers"
    DEBT_CONCENTRATION = "debt_concentration"
    WARD_MOVEMENTS = "ward_movements"


@dataclass(frozen=True)
class OverviewReportScope:
    """Filters of the Overview dashboard; ``date_to`` is exclusive like the analytics API."""

    topic: OverviewReportTopic
    date_from: date
    date_to: date
    customer_id: str | None = None
    ward: str | None = None
    village: str | None = None


@dataclass(frozen=True)
class OverviewReport:
    """Data block for the answering LLM plus the citations it may reference."""

    retrieved_text: str
    citations: list[dict[str, Any]] = field(default_factory=list)
