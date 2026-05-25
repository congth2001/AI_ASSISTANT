import json
import pandas as pd
from pathlib import Path


class AnalyticsRepository:
    """
    Pandas-based aggregation over raw transactions JSONL.

    Lazy-loads và cache DataFrame lần đầu truy cập.
    Dùng cho các query cần group-by / top-N / aggregate toàn bộ records
    trong 1 kỳ — không thể giải quyết bằng vector search top-k.
    """

    def __init__(self, data_path: str):
        self._data_path = data_path
        self._df: pd.DataFrame | None = None

    # ─────────────────────────────
    # Internal
    # ─────────────────────────────

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            self._df = self._load()
        return self._df

    def _load(self) -> pd.DataFrame:
        records: list[dict] = []
        with open(self._data_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                records.append(obj.get("metadata", {}))
        df = pd.DataFrame(records)
        # Đảm bảo các cột số đúng kiểu
        for col in ("year", "month", "day", "doanh_thu", "ghi_no"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def _filter_by_period(
        self,
        df: pd.DataFrame,
        month: int | None,
        year: int | None,
    ) -> pd.DataFrame:
        if year:
            df = df[df["year"] == year]
        if month:
            df = df[df["month"] == month]
        return df

    # ─────────────────────────────
    # Public queries
    # ─────────────────────────────

    def daily_revenue(self, month: int, year: int) -> pd.DataFrame:
        """Tổng doanh thu theo từng ngày trong tháng/năm."""
        df = self._filter_by_period(self.df, month, year)
        return (
            df.groupby("day")["doanh_thu"]
            .sum()
            .reset_index()
            .sort_values("day")
        )

    def top_customers(
        self,
        n: int,
        month: int | None = None,
        year: int | None = None,
    ) -> pd.DataFrame:
        """Top N khách hàng theo tổng doanh thu trong kỳ."""
        df = self._filter_by_period(self.df, month, year)
        group_cols = [c for c in ("customer_id", "ten_kh") if c in df.columns]
        return (
            df.groupby(group_cols)["doanh_thu"]
            .sum()
            .nlargest(n)
            .reset_index()
        )

    def monthly_revenue(self, year: int) -> pd.DataFrame:
        """Tổng doanh thu theo từng tháng trong năm."""
        df = self._filter_by_period(self.df, month=None, year=year)
        return (
            df.groupby("month")["doanh_thu"]
            .sum()
            .reset_index()
            .sort_values("month")
        )
