"""Build the data block for "Hỏi AI về khách này" on the customer debt-history page.

The numbers come from the same analytics port and domain services as
``GET /analytics/customers/{id}/debt-history`` (summary, FIFO aging, balance series)
and its ledger/revision endpoints, so the answer matches the page. The LLM only
explains them; no SQL is generated.
"""

import asyncio
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Sequence

from src.modules.analytics.domain.errors import CustomerNotFoundError, DebtLedgerTooLargeError
from src.modules.analytics.domain.models.customer_debt_history import (
    MAX_LEDGER_ENTRIES,
    DebtAgingBucketKey,
    DebtHistoryEntryFilters,
    DebtHistoryGrain,
    DebtStatus,
)
from src.modules.analytics.domain.repositories.i_customer_debt_history_repository import (
    ICustomerDebtHistoryRepository,
)
from src.modules.analytics.domain.repositories.i_dashboard_analytics_repository import (
    IDashboardAnalyticsRepository,
)
from src.modules.analytics.domain.services.debt_history import balance_series, fifo_aging, summarize
from src.modules.assistant.application.services.data_block import (
    DATA_BEGIN,
    DATA_END,
    format_cell,
    neutralize_delimiters,
)
from src.modules.assistant.domain.entities.overview_report import OverviewReport, OverviewReportScope
from src.modules.assistant.domain.errors import ReportCustomerRequiredError

SUMMARY = "report:debt_summary"
AGING = "report:debt_aging"
TREND = "report:debt_trend"
ENTRIES = "report:debt_entries"
REVISIONS = "report:debt_revisions"
FRESHNESS = "report:freshness"

_LABELS = {
    SUMMARY: "Tóm tắt công nợ của khách trong kỳ",
    AGING: "Tuổi nợ FIFO đến ngày cuối kỳ",
    TREND: "Số dư công nợ theo kỳ",
    ENTRIES: "Giao dịch gần nhất trong kỳ",
    REVISIONS: "Điều chỉnh hồi tố của các lần nạp dữ liệu",
    FRESHNESS: "Độ phủ dữ liệu",
}
_SECTIONS = (SUMMARY, AGING, TREND, ENTRIES, REVISIONS, FRESHNESS)

_STATUS = {
    DebtStatus.IN_DEBT: "Đang nợ",
    DebtStatus.CREDIT: "Dư có / ứng trước",
    DebtStatus.SETTLED: "Đã tất toán",
}
_AGING = {
    DebtAgingBucketKey.LE_3M: "≤ 3 tháng",
    DebtAgingBucketKey.M3_TO_6M: "3–6 tháng",
    DebtAgingBucketKey.M6_TO_1Y: "6 tháng – 1 năm",
    DebtAgingBucketKey.Y1_TO_2Y: "1–2 năm",
    DebtAgingBucketKey.Y2_TO_3Y: "2–3 năm",
    DebtAgingBucketKey.OVER_3Y: "> 3 năm",
}
_SOURCE = {
    "opening": "Số dư đầu kỳ",
    "sale": "Bán hàng",
    "sales_return": "Nhập trả",
    "receipt": "Thu nợ",
}

RECENT_ENTRIES = 15
RECENT_REVISIONS = 3
MAX_TREND_POINTS = 24
WEEKLY_TREND_MAX_DAYS = 92


def _day(value: date) -> str:
    return value.isoformat()


def _wall_clock(value: datetime) -> str:
    """``occurred_at`` is naive Vietnam time: print it as stored, never convert it."""
    return value.isoformat(sep=" ", timespec="minutes")


def _table(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    return [" | ".join(columns), *(" | ".join(format_cell(value) for value in row) for row in rows)]


def _trend_grain(first_day: date, as_of: date) -> DebtHistoryGrain:
    return DebtHistoryGrain.WEEK if (as_of - first_day).days <= WEEKLY_TREND_MAX_DAYS else DebtHistoryGrain.MONTH


class CustomerDebtReportBuilder:
    def __init__(
        self,
        history_repository: ICustomerDebtHistoryRepository,
        analytics_repository: IDashboardAnalyticsRepository,
    ):
        self._history = history_repository
        self._analytics = analytics_repository

    async def build(self, scope: OverviewReportScope) -> OverviewReport:
        if scope.customer_id is None:  # the request DTO already rejects this
            raise ReportCustomerRequiredError()
        customer_id = scope.customer_id
        as_of = scope.date_to - timedelta(days=1)  # scope.date_to is exclusive
        profile = await self._history.get_customer_profile(customer_id)
        if profile is None:
            raise CustomerNotFoundError()
        until = datetime.combine(scope.date_to, time.min)
        entries = await self._history.list_ledger_entries(customer_id, until, MAX_LEDGER_ENTRIES + 1)
        if len(entries) > MAX_LEDGER_ENTRIES:
            raise DebtLedgerTooLargeError(max_entries=MAX_LEDGER_ENTRIES)

        current_balance, revision_summary, (recent, has_more_entries), (revisions, more_revisions), freshness = (
            await asyncio.gather(
                self._history.get_current_balance(customer_id),
                self._history.get_revision_summary(customer_id),
                self._history.list_entry_page(
                    customer_id, DebtHistoryEntryFilters(date_from=scope.date_from, date_to=as_of),
                    None, RECENT_ENTRIES,
                ),
                self._history.list_customer_revisions(customer_id, None, RECENT_REVISIONS, 0),
                self._analytics.get_data_freshness(),
            )
        )
        summary = summarize(entries, scope.date_from, as_of, current_balance=current_balance)
        aging = fifo_aging(entries, as_of)
        first_day = scope.date_from or (entries[0].occurred_at.date() if entries else as_of)
        grain = _trend_grain(min(first_day, as_of), as_of)
        series = balance_series(entries, scope.date_from, as_of, grain)
        shown_series = series[-MAX_TREND_POINTS:]

        period_start = _day(scope.date_from) if scope.date_from else "đầu sổ công nợ"
        location = ", ".join(part for part in (profile.village_name, profile.ward_name) if part) or "chưa có địa bàn"
        lines = [
            "Câu hỏi từ trang Lịch sử công nợ của một khách hàng, số liệu tính sẵn bằng đúng truy vấn của trang.",
            f"Khách hàng: {neutralize_delimiters(profile.customer_name)} ({neutralize_delimiters(location)}; "
            f"customer_id={customer_id}).",
            f"Kỳ đang xem: từ {period_start} đến hết {_day(as_of)} (bao gồm hai đầu).",
            "Quy ước: số dư dương = khách đang nợ, số âm = khách ứng trước/dư có. Số dư lấy từ sổ công nợ "
            "(số dư đầu kỳ, bán chịu, thu nợ, nhập trả), lũy kế toàn sổ.",
            "",
            DATA_BEGIN,
            f"[{SUMMARY}] {_LABELS[SUMMARY]}",
            *_table(("chi_so", "gia_tri"), (
                ("so_du_dau_ky", summary.opening_balance),
                ("phat_sinh_tang", summary.increase_amount),
                ("thu_no", summary.receipt_amount),
                ("nhap_tra", summary.return_amount),
                ("giam_khac", summary.other_decrease_amount),
                ("so_du_cuoi_ky", summary.closing_balance),
                ("so_du_hien_tai_toan_so", summary.current_balance),
                ("trang_thai_cuoi_ky", _STATUS[summary.status]),
                ("no_lien_tuc_tu_ngay", _day(summary.debt_since) if summary.debt_since else None),
                ("so_ngay_no_lien_tuc", summary.days_in_debt),
                ("thu_no_gan_nhat_luc", _wall_clock(summary.last_receipt_at) if summary.last_receipt_at else None),
                ("so_tien_thu_no_gan_nhat", summary.last_receipt_amount),
            )),
            "Ghi chú: so_du_cuoi_ky = so_du_dau_ky + phat_sinh_tang - thu_no - nhap_tra - giam_khac. "
            "so_du_hien_tai_toan_so tính mọi bút toán, không phụ thuộc kỳ đang xem.",
            "",
            f"[{AGING}] {_LABELS[AGING]} ({_day(as_of)}): mọi khoản giảm trả cho khoản nợ cũ nhất trước; "
            "tổng các nhóm bằng số dư cuối kỳ khi số dư dương, bằng 0 khi không còn nợ.",
            *_table(("nhom_tuoi_no", "so_tien"), ((_AGING[bucket.bucket], bucket.amount) for bucket in aging)),
            "",
            f"[{TREND}] {_LABELS[TREND]} (nhóm theo {grain.value}"
            + (f", chỉ {len(shown_series)} kỳ gần nhất trên tổng {len(series)} kỳ" if len(series) > len(shown_series) else "")
            + ")",
            *_table(
                ("tu_ngay", "so_du_cuoi", "phat_sinh_tang", "phat_sinh_giam"),
                ((_day(p.period_start), p.closing_balance, p.increase, p.decrease) for p in shown_series),
            ),
            "",
            f"[{ENTRIES}] {_LABELS[ENTRIES]} (mới nhất trước, tối đa {RECENT_ENTRIES} dòng"
            + ("; còn giao dịch cũ hơn không hiển thị" if has_more_entries else "") + ")",
            *_table(
                ("thoi_diem", "loai", "so_chung_tu", "so_tien", "so_du_sau", "da_bi_sua_hoi_to"),
                ((_wall_clock(e.occurred_at), _SOURCE.get(e.source_type, e.source_type), e.voucher_number,
                  e.amount, e.balance_after, e.revised) for e, _cursor in recent),
            ),
            "",
            f"[{REVISIONS}] {_LABELS[REVISIONS]}: {revision_summary.revision_count} lần nạp đã sửa số liệu cũ "
            "của khách (chỉ ghi nhận từ lần nạp mốc sau khi bật lưu vết)"
            + (f", {len(revisions)} lần gần nhất:" if revisions else "."),
        ]
        if revisions:
            lines += _table(
                ("thoi_diem_nap", "so_du_truoc", "so_du_sau", "chenh_lech", "anh_huong_tu_ngay", "so_chung_tu_doi"),
                ((r.run_at.isoformat(timespec="minutes"), r.balance_before, r.balance_after, r.balance_delta,
                  _wall_clock(r.earliest_affected_at), r.change_count) for r in revisions),
            )
            if more_revisions:
                lines.append("Còn các lần điều chỉnh cũ hơn không hiển thị.")
        latest = freshness.latest_transaction_date
        coverage = (
            "không có giao dịch nào" if latest is None
            else f"ngày giao dịch mới nhất toàn hệ thống là {_day(latest)}"
            + (f"; kỳ đang xem kết thúc {_day(as_of)}, sau ngày này chưa có dữ liệu" if latest < as_of else "")
        )
        lines += ["", f"[{FRESHNESS}] {_LABELS[FRESHNESS]}: {coverage}.", DATA_END]

        citations = [{"id": section, "type": "report", "label": _LABELS[section]} for section in _SECTIONS]
        return OverviewReport(retrieved_text="\n".join(lines), citations=citations)
