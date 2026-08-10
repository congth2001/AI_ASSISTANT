from dataclasses import dataclass
from typing import Optional


@dataclass
class TimeFilter:
    day   : Optional[int] = None
    year  : Optional[int] = None
    month : Optional[int] = None
    quarter: Optional[int] = None

    def to_milvus_expr(self) -> str:
        parts = []
        if self.day:
            parts.append(f"day == {self.day}")
        if self.year:
            parts.append(f"year == {self.year}")
        if self.month:
            parts.append(f"month == {self.month}")
        if self.quarter:
            # quarter 1 = month 1,2,3 — dùng range thay vì quarter field
            q = self.quarter
            m_start = (q - 1) * 3 + 1
            m_end   = q * 3
            parts.append(f"(month >= {m_start} && month <= {m_end})")
        return " && ".join(parts)

    @property
    def is_empty(self) -> bool:
        return not any([self.day, self.year, self.month, self.quarter])