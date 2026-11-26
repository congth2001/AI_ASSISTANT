"""Build the data block for Overview-dashboard questions from the dashboard's own queries.

The preset "Hỏi AI" questions of the Overview screen ask about numbers the
dashboard already computes deterministically. Letting the LLM regenerate them as
several complex SQL plans was slow and often contradicted the screen (e.g. revenue
summed after a line join). Here the numbers come from the same analytics
repository and period logic as the dashboard; the LLM only explains them.
"""

import asyncio
from datetime import date, timedelta
from typing import Any, Iterable, Sequence

from src.modules.analytics.domain.models.dashboard import DashboardFilters, TimeGrain
from src.modules.analytics.domain.repositories.i_dashboard_analytics_repository import (
    IDashboardAnalyticsRepository,
)
from src.modules.analytics.domain.services.period_comparison import (
    align_period_series,
    summarize_periods,
)
from src.modules.assistant.application.services.data_block import (
    DATA_BEGIN,
    DATA_END,
    format_cell,
    neutralize_delimiters,
)
from src.modules.assistant.domain.errors import InvalidReportPeriodError
from src.modules.assistant.domain.entities.overview_report import (
    MAX_REPORT_DAYS,
    OverviewReport,
    OverviewReportScope,
    OverviewReportTopic,
)

KPI = "report:kpi"
TREND = "report:trend"
CUSTOMERS = "report:customers"
DEBT = "report:debt"
WARDS = "report:wards"
FRESHNESS = "report:freshness"

_LABELS = {
    KPI: "KPI kỳ hiện tại so với kỳ trước",
    TREND: "Doanh thu hai kỳ theo từng giai đoạn",
    CUSTOMERS: "Khách hàng giảm doanh thu",
    DEBT: "Tập trung công nợ phải thu",
    WARDS: "Biến động doanh thu theo phường/xã",
    FRESHNESS: "Độ phủ dữ liệu",
}
# Sections per preset question; KPI and data coverage give every answer its frame.
_SECTIONS = {
    OverviewReportTopic.BUSINESS_OVERVIEW: (KPI, TREND, CUSTOMERS, DEBT, WARDS, FRESHNESS),
    OverviewReportTopic.DECLINING_CUSTOMERS: (KPI, CUSTOMERS, FRESHNESS),
    OverviewReportTopic.DEBT_CONCENTRATION: (DEBT, FRESHNESS),
    OverviewReportTopic.WARD_MOVEMENTS: (KPI, WARDS, FRESHNESS),
}


def _day(value: date) -> str:
    return value.isoformat()


def _last_day(exclusive_end: date) -> str:
    return _day(exclusive_end - timedelta(days=1))


def _table(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    return [" | ".join(columns), *(" | ".join(format_cell(value) for value in row) for row in rows)]


def _trend_grain(day_count: int) -> TimeGrain:
    if day_count <= 31:
        return TimeGrain.WEEK
    if day_count <= 366:
        return TimeGrain.MONTH
    return TimeGrain.QUARTER


class OverviewReportBuilder:
    def __init__(self, repository: IDashboardAnalyticsRepository):
        self._repository = repository

    async def build(self, scope: OverviewReportScope) -> OverviewReport:
        if scope.date_from is None:  # the request DTO already rejects this for Overview topics
            raise InvalidReportPeriodError(max_days=MAX_REPORT_DAYS)
        filters = DashboardFilters(
            date_from=scope.date_from,
            date_to=scope.date_to,
            customer_id=scope.customer_id,
            ward_names=(scope.ward,) if scope.ward else (),
            village_names=(scope.village,) if scope.village else (),
        )
        previous = filters.previous_period()
        sections = _SECTIONS[scope.topic]
        repo = self._repository
        current_kpi, previous_kpi, insights, freshness, current_days, previous_days = await asyncio.gather(
            repo.get_metric_snapshot(filters),
            repo.get_metric_snapshot(previous),
            repo.get_overview_insights(filters),
            repo.get_data_freshness(),
            repo.get_time_series(filters, TimeGrain.DAY) if TREND in sections else _nothing(),
            repo.get_time_series(previous, TimeGrain.DAY) if TREND in sections else _nothing(),
        )
        summary = summarize_periods(current_kpi, previous_kpi)

        lines = [
            "Câu hỏi từ dashboard Tổng quan, số liệu tính sẵn bằng đúng truy vấn của dashboard.",
            f"Kỳ hiện tại: {_day(filters.date_from)} đến hết {_last_day(filters.date_to)} "
            f"({filters.day_count} ngày). Kỳ trước cùng số ngày: {_day(previous.date_from)} "
            f"đến hết {_last_day(previous.date_to)}.",
            "Bộ lọc: khách hàng " + (neutralize_delimiters(scope.customer_id) if scope.customer_id else "tất cả")
            + "; phường/xã " + (neutralize_delimiters(scope.ward) if scope.ward else "tất cả")
            + "; thôn/xóm " + (neutralize_delimiters(scope.village) if scope.village else "tất cả") + ".",
            "Doanh thu = tổng hóa đơn bán + nhập trả (số âm) trong kỳ; phải thu = tổng số dư dương từng khách "
            "lũy kế đến hết kỳ.",
            "",
            DATA_BEGIN,
        ]
        if KPI in sections:
            growth = summary.revenue_growth_percent
            lines += [f"[{KPI}] {_LABELS[KPI]}", *_table(
                ("chi_so", "ky_hien_tai", "ky_truoc", "chenh_lech", "ty_le_tang_truong_phan_tram"),
                (
                    ("doanh_thu_thuan", current_kpi.total_revenue, previous_kpi.total_revenue,
                     summary.revenue_change, growth),
                    ("so_hoa_don_ban", current_kpi.invoice_count, previous_kpi.invoice_count,
                     current_kpi.invoice_count - previous_kpi.invoice_count, None),
                    ("so_khach_mua", current_kpi.customer_count, previous_kpi.customer_count,
                     current_kpi.customer_count - previous_kpi.customer_count, None),
                    ("gia_tri_hoa_don_binh_quan", current_kpi.average_invoice_value,
                     previous_kpi.average_invoice_value,
                     current_kpi.average_invoice_value - previous_kpi.average_invoice_value, None),
                    ("phai_thu_tang_giam_trong_ky", current_kpi.net_debt_delta,
                     previous_kpi.net_debt_delta, None, None),
                ),
            ),
                "Ghi chú: phai_thu_tang_giam_trong_ky = tổng bút toán sổ công nợ trong kỳ (bán chịu, thu nợ, "
                "trả hàng). Số dương = phải thu TĂNG (bán chịu nhiều hơn tiền thu về), số âm = phải thu GIẢM.",
                ""]
        if TREND in sections:
            grain = _trend_grain(filters.day_count)
            points = align_period_series(filters, grain, current_days, previous_days)
            lines += [f"[{TREND}] {_LABELS[TREND]} (nhóm theo {grain.value}, ghép theo thứ tự ngày)", *_table(
                ("tu_ngay", "den_het_ngay", "doanh_thu", "doanh_thu_ky_truoc", "so_hoa_don", "so_hoa_don_ky_truoc"),
                ((_day(p.period_start), _last_day(p.period_end), p.revenue, p.previous_revenue,
                  p.invoice_count, p.previous_invoice_count) for p in points),
            ), ""]
        if CUSTOMERS in sections:
            lines += [
                f"[{CUSTOMERS}] {_LABELS[CUSTOMERS]}: {insights.declining_customer_count} khách có doanh thu kỳ "
                f"trước và giảm trong kỳ này, tổng mức giảm {format_cell(insights.declining_revenue_change)} VND; "
                f"{insights.inactive_customer_count} khách trong nhóm này không có hóa đơn bán trong kỳ. "
                "Top giảm mạnh nhất:",
                *_table(
                    ("ten_khach_hang", "phuong_xa", "thon_xom", "doanh_thu_ky_truoc", "doanh_thu_ky_nay",
                     "chenh_lech", "so_hoa_don_ky_truoc", "so_hoa_don_ky_nay"),
                    ((c.customer_name, c.ward_name, c.village_name, c.previous_revenue, c.current_revenue,
                      c.revenue_change, c.previous_invoice_count, c.current_invoice_count)
                     for c in insights.declining_customers),
                ),
                "",
            ]
        if DEBT in sections:
            share = insights.top_receivables_share_percent
            lines += [
                f"[{DEBT}] {_LABELS[DEBT]} đến hết {_last_day(filters.date_to)}: tổng phải thu "
                f"{format_cell(insights.total_receivables)} VND từ {insights.debtor_count} khách còn nợ; "
                f"top {len(insights.debt_customers)} chiếm {format_cell(insights.top_receivables)} VND"
                + (f" ({format_cell(share)}%)." if share is not None else "."),
                *_table(
                    ("ten_khach_hang", "phuong_xa", "thon_xom", "phai_thu"),
                    ((c.customer_name, c.ward_name, c.village_name, c.receivables) for c in insights.debt_customers),
                ),
                "",
            ]
        if WARDS in sections:
            lines += [f"[{WARDS}] {_LABELS[WARDS]} (top theo độ lớn chênh lệch)", *_table(
                ("phuong_xa", "doanh_thu_ky_nay", "doanh_thu_ky_truoc", "chenh_lech"),
                ((w.ward_name or "(chưa có phường/xã)", w.current_revenue, w.previous_revenue, w.revenue_change)
                 for w in insights.ward_movements),
            ), ""]
        latest = freshness.latest_transaction_date
        coverage = (
            "không có giao dịch nào" if latest is None
            else f"ngày giao dịch mới nhất toàn hệ thống là {_day(latest)}"
            + (f"; kỳ đang xem kết thúc {_last_day(filters.date_to)}, sau ngày này chưa có dữ liệu, "
               "không được coi là suy giảm kinh doanh đã xác nhận" if latest < filters.date_to - timedelta(days=1) else "")
        )
        lines += [f"[{FRESHNESS}] {_LABELS[FRESHNESS]}: {coverage}.", DATA_END]

        citations = [{"id": section, "type": "report", "label": _LABELS[section]} for section in sections]
        return OverviewReport(retrieved_text="\n".join(lines), citations=citations)


async def _nothing() -> list:
    return []

