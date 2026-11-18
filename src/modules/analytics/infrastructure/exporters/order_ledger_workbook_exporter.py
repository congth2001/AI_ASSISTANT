"""OpenPyXL adapter for the single-customer transaction ledger workbook."""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, NamedStyle
from openpyxl.utils import get_column_letter

from src.modules.analytics.domain.models.order_ledger import (
    OrderLedgerExportData,
    OrderLedgerExportFilters,
)
from src.modules.analytics.domain.ports.i_order_ledger_workbook_exporter import (
    IOrderLedgerWorkbookExporter,
)
from src.modules.analytics.domain.errors import (
    OrderLedgerRowLimitError,
)
from src.modules.analytics.domain.models.export_limits import MAX_SHEET_DATA_ROWS
from src.modules.analytics.infrastructure.exporters.xlsx_common import (
    clean_sheet_name,
    truncate_sheet_name,
    write_text,
)


class OpenpyxlOrderLedgerWorkbookExporter(IOrderLedgerWorkbookExporter):
    MAX_DATA_ROWS = MAX_SHEET_DATA_ROWS
    HEADERS = (
        "Ngày",
        "Số phiếu",
        "Lý do",
        "Tên hàng",
        "ĐVT",
        "Đơn giá",
        "Số lượng",
        "Thanh toán",
        "Ghi nợ",
        "Nợ cộng dồn",
    )
    ACCOUNTING_FORMAT = '_(* #,##0_);_(* \\(#,##0\\);_(* "-"??_);_(@_)'
    DATE_TIME_FORMAT = "d/m/yyyy h:mm AM/PM"

    def build(
        self,
        data: OrderLedgerExportData,
        _filters: OrderLedgerExportFilters,
    ) -> bytes:
        if len(data.items) > self.MAX_DATA_ROWS:
            raise OrderLedgerRowLimitError(max_rows=self.MAX_DATA_ROWS)

        workbook = Workbook()
        self._register_styles(workbook)
        worksheet = workbook.active
        worksheet.title = self._sheet_name(data.customer_name)

        metadata = (
            ("Tên đối tác:", data.customer_name),
            ("Địa chỉ:", data.customer_address or ""),
            (
                "Ngày xuất file:",
                datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).replace(tzinfo=None),
            ),
        )
        for row_number, (label, value) in enumerate(metadata, start=1):
            label_cell = worksheet.cell(row=row_number, column=1, value=label)
            label_cell.style = "ledger_label"
            value_cell = worksheet.cell(row=row_number, column=2)
            value_cell.style = "ledger_meta_value"
            if isinstance(value, str):
                write_text(value_cell, value)
            else:
                value_cell.value = value
        worksheet["B3"].number_format = self.DATE_TIME_FORMAT

        for column, header in enumerate(self.HEADERS, start=1):
            worksheet.cell(row=6, column=column, value=header).style = "ledger_label"

        previous_event_key: tuple | None = None
        row_number = 7
        for item in data.items:
            event_key = (item.occurred_at, item.voucher_number, item.reason)
            first_event_row = event_key != previous_event_key
            previous_event_key = event_key
            occurred_at = item.occurred_at
            if occurred_at.tzinfo is not None:
                occurred_at = occurred_at.replace(tzinfo=None)
            cells = [
                worksheet.cell(row=row_number, column=column) for column in range(1, 11)
            ]
            for cell in cells[:5]:
                cell.style = "ledger_body"
            cells[0].style = "ledger_date"
            for cell in cells[5:]:
                cell.style = "ledger_money"
            cells[6].style = "ledger_body"  # quantity keeps its decimals
            if first_event_row:
                cells[0].value = occurred_at
                write_text(cells[1], item.voucher_number)
                write_text(cells[2], item.reason)
                cells[7].value = self._rounded_money(item.payment_amount)
                cells[8].value = self._rounded_money(item.debt_amount)
                cells[9].value = self._rounded_money(item.running_debt)
            if item.product_name:
                write_text(cells[3], item.product_name)
            if item.unit_name:
                write_text(cells[4], item.unit_name)
            cells[5].value = self._rounded_money(item.unit_price)
            cells[6].value = item.quantity
            row_number += 1

        if not data.items:
            worksheet.cell(row=7, column=1, value="Không có giao dịch phù hợp với bộ lọc.")
            worksheet["A7"].font = Font(name="Arial", size=11, italic=True)

        widths = (18.875, 25, 8.75, 37, 13, 13.25, 9.25, 14.25, 15, 15.25)
        for column, width in enumerate(widths, start=1):
            worksheet.column_dimensions[get_column_letter(column)].width = width

        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    @classmethod
    def _register_styles(cls, workbook: Workbook) -> None:
        font = Font(name="Arial", size=11)
        bold = Font(name="Arial", size=11, bold=True)
        workbook.add_named_style(NamedStyle(name="ledger_label", font=bold))
        workbook.add_named_style(NamedStyle(
            name="ledger_meta_value", font=font, alignment=Alignment(horizontal="right"),
        ))
        workbook.add_named_style(NamedStyle(name="ledger_body", font=font))
        workbook.add_named_style(NamedStyle(
            name="ledger_date", font=font, number_format=cls.DATE_TIME_FORMAT,
        ))
        workbook.add_named_style(NamedStyle(
            name="ledger_money", font=font, number_format=cls.ACCOUNTING_FORMAT,
        ))

    @staticmethod
    def _sheet_name(customer_name: str) -> str:
        suffix = "_DoiTac"
        safe_name = clean_sheet_name(customer_name, fallback="DoiTac", replacement=" ")
        prefix = safe_name[: 31 - len(suffix)].strip(" '")
        return truncate_sheet_name(f"{prefix}{suffix}")

    @staticmethod
    def _rounded_money(value: Decimal) -> int:
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
