from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.modules.assistant.domain.errors import InvalidReportPeriodError, ReportCustomerRequiredError
from src.modules.assistant.domain.entities.overview_report import (
    MAX_REPORT_DAYS,
    OverviewReportScope,
    OverviewReportTopic,
)

MAX_CHAT_MESSAGE_LENGTH = 4000


class ReportContextRequest(BaseModel):
    """Filters of the screen behind a preset "Hỏi AI" question.

    When present, the answer is built from the dashboard's own numbers instead of
    LLM-generated SQL. Dates follow the analytics API: ``date_to`` is exclusive.
    Overview topics need ``date_from``. ``customer_debt_history`` needs ``customer_id``,
    accepts no ``date_from`` (whole ledger) and ignores ``ward``/``village``.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    topic: OverviewReportTopic
    date_from: Optional[date] = None
    date_to: date = Field(description="Exclusive end date, like the analytics API")
    customer_id: Optional[UUID] = None
    ward: Optional[str] = Field(default=None, max_length=200)
    village: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def check_period(self) -> "ReportContextRequest":
        debt_history = self.topic is OverviewReportTopic.CUSTOMER_DEBT_HISTORY
        if debt_history and self.customer_id is None:
            raise ReportCustomerRequiredError()
        if self.date_from is None:
            if not debt_history:
                raise InvalidReportPeriodError(max_days=MAX_REPORT_DAYS)
        elif self.date_to <= self.date_from or (self.date_to - self.date_from).days > MAX_REPORT_DAYS:
            raise InvalidReportPeriodError(max_days=MAX_REPORT_DAYS)
        return self

    def to_scope(self) -> OverviewReportScope:
        return OverviewReportScope(
            topic=self.topic,
            date_from=self.date_from,
            date_to=self.date_to,
            customer_id=str(self.customer_id) if self.customer_id else None,
            ward=self.ward or None,
            village=self.village or None,
        )


class ChatRequest(BaseModel):
    # Clients written against the older contract may still send ``user_id``;
    # identity always comes from the Bearer token, so unknown fields are ignored.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    conversation_id: Optional[str] = None
    message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_LENGTH)
    report_context: Optional[ReportContextRequest] = None
