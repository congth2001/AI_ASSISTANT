from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional


@dataclass
class DateRange:
    """Value object representing a date range"""
    start_date: date
    end_date: date

    def __post_init__(self):
        if self.start_date > self.end_date:
            raise ValueError("Start date must be before or equal to end date")

    @property
    def days(self) -> int:
        """Calculate the number of days in the range"""
        return (self.end_date - self.start_date).days + 1

    @classmethod
    def from_dates(cls, start: date, end: date) -> 'DateRange':
        return cls(start_date=start, end_date=end)

    @classmethod
    def last_n_days(cls, n: int, reference_date: Optional[date] = None) -> 'DateRange':
        if reference_date is None:
            reference_date = date.today()
        start_date = reference_date - datetime.timedelta(days=n-1)
        return cls(start_date=start_date, end_date=reference_date)

    @classmethod
    def current_month(cls) -> 'DateRange':
        today = date.today()
        start_date = today.replace(day=1)
        # Get last day of current month
        next_month = start_date.replace(month=start_date.month % 12 + 1, day=1)
        end_date = next_month - datetime.timedelta(days=1)
        return cls(start_date=start_date, end_date=end_date)