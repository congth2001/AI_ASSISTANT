from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.entities.time_filter import TimeFilter
from src.domain.value_objects.aggregation_type import AggregationType
from src.infrastructure.repositories.analytics_repository import AnalyticsRepository


class AnalyticsUseCase:
    """
    Xử lý các query cần aggregate toàn bộ raw transactions (group-by, top-N, max/min).

    Input : AnalyzedQuery với needs_analytics=True
    Output: str — bảng dữ liệu đã format, inject vào system prompt của LLM
    """

    def __init__(self, analytics_repo: AnalyticsRepository):
        self.repo = analytics_repo

    def execute(self, analyzed: AnalyzedQuery) -> str:
        agg = analyzed.aggregation_type
        tf  = analyzed.time_filter

        if agg == AggregationType.DAILY_REVENUE:
            return self._daily_revenue(tf)
        if agg == AggregationType.TOP_CUSTOMERS:
            return self._top_customers(analyzed.top_n, tf)
        if agg == AggregationType.MONTHLY_REVENUE:
            return self._monthly_revenue(tf)
        return ""

    # ─────────────────────────────
    # Aggregation formatters
    # ─────────────────────────────

    def _daily_revenue(self, tf: TimeFilter) -> str:
        if not tf.month or not tf.year:
            return "Thiếu thông tin tháng/năm để tổng hợp doanh thu theo ngày."

        df = self.repo.daily_revenue(tf.month, tf.year)
        if df.empty:
            return f"Không có dữ liệu giao dịch tháng {tf.month}/{tf.year}."

        lines = [f"Doanh thu theo ngày — Tháng {tf.month}/{tf.year}:"]
        for _, row in df.iterrows():
            lines.append(f"  Ngày {int(row['day']):02d}: {int(row['doanh_thu']):,} VND")

        max_row = df.loc[df["doanh_thu"].idxmax()]
        min_row = df.loc[df["doanh_thu"].idxmin()]
        lines.append(
            f"\nCao nhất : Ngày {int(max_row['day']):02d} — {int(max_row['doanh_thu']):,} VND"
        )
        lines.append(
            f"Thấp nhất: Ngày {int(min_row['day']):02d} — {int(min_row['doanh_thu']):,} VND"
        )
        return "\n".join(lines)

    def _top_customers(self, n: int, tf: TimeFilter) -> str:
        df = self.repo.top_customers(n, tf.month, tf.year)
        if df.empty:
            return "Không có dữ liệu phù hợp."

        period = self._period_label(tf)
        lines = [f"Top {n} khách hàng theo doanh thu{period}:"]
        for rank, (_, row) in enumerate(df.iterrows(), 1):
            name = row.get("ten_kh") or row["customer_id"]
            lines.append(f"  {rank:2d}. {name}: {int(row['doanh_thu']):,} VND")
        return "\n".join(lines)

    def _monthly_revenue(self, tf: TimeFilter) -> str:
        if not tf.year:
            return "Thiếu thông tin năm để tổng hợp doanh thu theo tháng."

        df = self.repo.monthly_revenue(tf.year)
        if df.empty:
            return f"Không có dữ liệu giao dịch năm {tf.year}."

        lines = [f"Doanh thu theo tháng — Năm {tf.year}:"]
        for _, row in df.iterrows():
            lines.append(f"  Tháng {int(row['month']):02d}: {int(row['doanh_thu']):,} VND")

        max_row = df.loc[df["doanh_thu"].idxmax()]
        min_row = df.loc[df["doanh_thu"].idxmin()]
        lines.append(
            f"\nCao nhất : Tháng {int(max_row['month']):02d} — {int(max_row['doanh_thu']):,} VND"
        )
        lines.append(
            f"Thấp nhất: Tháng {int(min_row['month']):02d} — {int(min_row['doanh_thu']):,} VND"
        )
        return "\n".join(lines)

    # ─────────────────────────────
    # Helper
    # ─────────────────────────────

    @staticmethod
    def _period_label(tf: TimeFilter) -> str:
        if tf.month and tf.year:
            return f" — Tháng {tf.month}/{tf.year}"
        if tf.quarter and tf.year:
            return f" — Quý {tf.quarter}/{tf.year}"
        if tf.year:
            return f" — Năm {tf.year}"
        return ""
