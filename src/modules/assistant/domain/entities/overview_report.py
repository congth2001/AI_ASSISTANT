"""Dashboard questions answered from the dashboard's own numbers (no generated SQL)."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

# Longest report period accepted from the client.
MAX_REPORT_DAYS = 3660


class OverviewReportTopic(str, Enum):
    """Preset "Hỏi AI" questions: four on the Overview dashboard, one on a customer's debt page."""

    BUSINESS_OVERVIEW = "business_overview"
    DECLINING_CUSTOMERS = "declining_customers"
    DEBT_CONCENTRATION = "debt_concentration"
    WARD_MOVEMENTS = "ward_movements"
    CUSTOMER_DEBT_HISTORY = "customer_debt_history"


@dataclass(frozen=True)
class OverviewReportScope:
    """Filters of the screen asking; ``date_to`` is exclusive like the analytics API.

    ``date_from`` is always set for Overview topics. For ``CUSTOMER_DEBT_HISTORY`` it may be
    None (the whole ledger), ``customer_id`` is required and ``ward``/``village`` are unused.
    """

    topic: OverviewReportTopic
    date_from: date | None
    date_to: date
    customer_id: str | None = None
    ward: str | None = None
    village: str | None = None


@dataclass(frozen=True)
class OverviewReport:
    """Data block for the answering LLM plus the citations it may reference."""

    retrieved_text: str
    citations: list[dict[str, Any]] = field(default_factory=list)
