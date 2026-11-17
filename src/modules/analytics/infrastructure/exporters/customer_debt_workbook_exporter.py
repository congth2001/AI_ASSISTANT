"""OpenPyXL adapter for customer debt workbooks."""

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, NamedStyle, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.modules.analytics.domain.models.customer_debt import (
    CustomerDebtExportFilters,
    CustomerDebtExportItem,
    CustomerDebtSheetMode,
)
from src.modules.analytics.domain.ports.i_customer_debt_workbook_exporter import (
    ICustomerDebtWorkbookExporter,
)
from src.modules.analytics.domain.errors import (
    CustomerDebtRowLimitError,
    ExportWorkbookRowLimitError,
)
from src.modules.analytics.domain.models.export_limits import (
    MAX_SHEET_DATA_ROWS,
    MAX_WORKBOOK_DATA_ROWS,
)
from src.modules.analytics.infrastructure.exporters.xlsx_common import (
    clean_sheet_name,
    truncate_sheet_name,
    write_text,
)

DARK_BLUE = "17365D"
HEADER_BLUE = "2F75B5"
PALE_BLUE = "D9EAF7"
MONEY_FORMAT = '#,##0;[Red]-#,##0'


class OpenpyxlCustomerDebtWorkbookExporter(ICustomerDebtWorkbookExporter):
    MAX_DATA_ROWS = MAX_SHEET_DATA_ROWS
    MAX_TOTAL_ROWS = MAX_WORKBOOK_DATA_ROWS
    HEADERS = (
        "STT",
        "Khách hàng",
        "Phường/xã",
        "Thôn/xóm",
        "Địa chỉ",
        "Công nợ",
    )

    def build(
        self,
        items: list[CustomerDebtExportItem],
        filters: CustomerDebtExportFilters,
    ) -> bytes:
        groups = self._group_items(items, filters)
        # Validate sizes before creating a single cell.
        for raw_name, sheet_items in groups:
            if len(sheet_items) > self.MAX_DATA_ROWS:
                raise CustomerDebtRowLimitError(raw_name=raw_name, max_rows=self.MAX_DATA_ROWS)
        if sum(len(sheet_items) for _, sheet_items in groups) > self.MAX_TOTAL_ROWS:
            raise ExportWorkbookRowLimitError(max_rows=self.MAX_TOTAL_ROWS)

        workbook = Workbook()
        workbook.remove(workbook.active)
        self._register_styles(workbook)
        used_names: set[str] = set()

        for raw_name, sheet_items in groups:
            sheet_name = self._unique_sheet_name(raw_name, used_names)
            worksheet = workbook.create_sheet(sheet_name)
            self._populate_sheet(worksheet, sheet_items, filters)

        workbook.calculation.fullCalcOnLoad = True
        workbook.calculation.forceFullCalc = True
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    def _group_items(
        self,
        items: list[CustomerDebtExportItem],
        filters: CustomerDebtExportFilters,
    ) -> list[tuple[str, list[CustomerDebtExportItem]]]:
        all_items = self._sort_by_debt(items)
        if filters.sheet_mode == CustomerDebtSheetMode.SINGLE:
            return [("All", all_items)]

        groups: dict[tuple[str, ...], list[CustomerDebtExportItem]] = defaultdict(list)
        if filters.sheet_mode == CustomerDebtSheetMode.VILLAGE:
            for item in items:
                groups[(item.ward_name or "Không rõ xã", item.village_name or "Không rõ thôn")].append(item)
            return [("All", all_items), *[
                (f"{village} - {ward}", self._sort_by_debt(group))
                for (ward, village), group in sorted(groups.items())
            ]]

        for item in items:
            groups[(item.ward_name or "Không rõ xã",)].append(item)
        return [("All", all_items), *[
            (ward, sorted(group, key=lambda item: (
                (item.village_name or "").casefold(),
                -item.current_debt,
                item.label.casefold(),
            )))
            for (ward,), group in sorted(groups.items())
        ]]

    @staticmethod
    def _sort_by_debt(
        items: list[CustomerDebtExportItem],
    ) -> list[CustomerDebtExportItem]:
        return sorted(items, key=lambda item: (-item.current_debt, item.label.casefold()))

    @staticmethod
    def _unique_sheet_name(raw_name: str, used_names: set[str]) -> str:
        base = truncate_sheet_name(clean_sheet_name(raw_name, fallback="Sheet"))
        candidate = base
        suffix = 2
        while candidate.casefold() in used_names:
            marker = f" ({suffix})"
            candidate = truncate_sheet_name(f"{base[:31 - len(marker)]}{marker}")
            suffix += 1
        used_names.add(candidate.casefold())
        return candidate

    @staticmethod
    def _register_styles(workbook: Workbook) -> None:
        """Create each style once per workbook; cells only reference them by name."""
        body_font = Font(name="Aptos", size=10)
        border = Border(bottom=Side(style="thin", color="D9E2F3"))
        for name, horizontal, number_format in (
            ("debt_body_text", "left", "General"),
            ("debt_body_right", "right", "General"),
            ("debt_body_money", "right", MONEY_FORMAT),
        ):
            workbook.add_named_style(NamedStyle(
                name=name, font=body_font, border=border, number_format=number_format,
                alignment=Alignment(horizontal=horizontal, vertical="center"),
            ))
        workbook.add_named_style(NamedStyle(
            name="debt_title",
            font=Font(name="Aptos Display", size=16, bold=True, color="FFFFFF"),
            fill=PatternFill("solid", fgColor=DARK_BLUE),
            alignment=Alignment(horizontal="center", vertical="center"),
        ))
        workbook.add_named_style(NamedStyle(
            name="debt_period",
            font=Font(name="Aptos", size=10, italic=True, color="44546A"),
            fill=PatternFill("solid", fgColor=PALE_BLUE),
            alignment=Alignment(horizontal="left", vertical="center"),
        ))
        workbook.add_named_style(NamedStyle(
            name="debt_header",
            font=Font(name="Aptos", size=10, bold=True, color="FFFFFF"),
            fill=PatternFill("solid", fgColor=HEADER_BLUE),
            alignment=Alignment(horizontal="center", vertical="center"),
        ))
        workbook.add_named_style(NamedStyle(
            name="debt_total_label",
            font=Font(name="Aptos", size=10, bold=True, color=DARK_BLUE),
            alignment=Alignment(horizontal="right"),
        ))
        workbook.add_named_style(NamedStyle(
            name="debt_total_value",
            font=Font(name="Aptos", size=10, bold=True, color=DARK_BLUE),
            fill=PatternFill("solid", fgColor=PALE_BLUE),
            number_format=MONEY_FORMAT,
            alignment=Alignment(horizontal="right"),
        ))

    def _populate_sheet(
        self,
        worksheet,
        items: list[CustomerDebtExportItem],
        filters: CustomerDebtExportFilters,
    ) -> None:
        worksheet.sheet_view.showGridLines = False
        worksheet.freeze_panes = "A5"
        worksheet.sheet_properties.tabColor = HEADER_BLUE
        worksheet.merge_cells("A1:F1")
        worksheet["A1"] = "DANH SÁCH KHÁCH HÀNG VÀ CÔNG NỢ"
        worksheet["A1"].style = "debt_title"
        worksheet.row_dimensions[1].height = 28

        worksheet.merge_cells("A2:F2")
        worksheet["A2"] = self._period_label(filters.date_from, filters.date_to)
        worksheet["A2"].style = "debt_period"
        worksheet.row_dimensions[2].height = 21

        for column, header in enumerate(self.HEADERS, start=1):
            cell = worksheet.cell(row=4, column=column, value=header)
            cell.style = "debt_header"
        worksheet.row_dimensions[4].height = 23

        first_data_row = 5
        for index, item in enumerate(items, start=1):
            row = first_data_row + index - 1
            cell = worksheet.cell(row=row, column=1, value=index)
            cell.style = "debt_body_right"
            for column, text in enumerate(
                (item.label, item.ward_name, item.village_name, item.address_detail), start=2
            ):
                cell = worksheet.cell(row=row, column=column)
                cell.style = "debt_body_text"
                write_text(cell, text)  # after the style: it may set quotePrefix
            cell = worksheet.cell(row=row, column=6, value=self._rounded_debt(item.current_debt))
            cell.style = "debt_body_money"

        last_data_row = first_data_row + len(items) - 1
        total_row = max(first_data_row, last_data_row + 1)
        worksheet.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=5)
        label_cell = worksheet.cell(row=total_row, column=1, value=f"Tổng cộng ({len(items)} khách hàng)")
        label_cell.style = "debt_total_label"
        total_cell = worksheet.cell(row=total_row, column=6)
        total_cell.value = f"=SUM(F{first_data_row}:F{last_data_row})" if items else 0
        total_cell.style = "debt_total_value"

        widths = (8, 32, 22, 24, 42, 20)
        for column, width in enumerate(widths, start=1):
            worksheet.column_dimensions[get_column_letter(column)].width = width
        worksheet.auto_filter.ref = f"A4:F{max(4, last_data_row)}"

    @staticmethod
    def _period_label(date_from: date | None, date_to: date | None) -> str:
        if not date_from and not date_to:
            return "Kỳ công nợ: Tất cả thời gian"
        start = date_from.strftime("%d/%m/%Y") if date_from else "đầu kỳ dữ liệu"
        end = date_to.strftime("%d/%m/%Y") if date_to else "hiện tại"
        return f"Kỳ công nợ: {start} - {end} (bao gồm hai đầu ngày)"

    @staticmethod
    def _rounded_debt(value: Decimal) -> int:
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
