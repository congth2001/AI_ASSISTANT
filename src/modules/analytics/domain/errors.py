"""Central catalog of analytics error codes and message templates."""
from src.common.errors import (
    NotFoundError,
    ValidationError,
)


class CursorPaginationConflictError(ValidationError):
    code = 'cursor_pagination_conflict'
    message_template = 'Cursor and offset cannot be used together'


class InvalidCursorValuesError(ValidationError):
    code = 'invalid_cursor_values'
    message_template = 'Invalid cursor values'


class InvalidCustomerOverviewCursorError(ValidationError):
    code = 'invalid_customer_overview_cursor'
    message_template = 'Invalid customer overview cursor'


class InvalidExportDateRangeError(ValidationError):
    code = 'invalid_export_date_range'
    message_template = 'date_from must be before or equal to date_to'


class VillageWardRequiredError(ValidationError):
    code = 'village_ward_required'
    message_template = 'Village sheets require at least one ward filter'


class InvalidReportDateRangeError(ValidationError):
    code = 'invalid_report_date_range'
    message_template = 'date_from must be before date_to'


class OverviewDimensionsUnsupportedError(ValidationError):
    code = 'overview_dimensions_unsupported'
    message_template = 'Overview insights support customer and geography filters only'


class CustomerDebtRowLimitError(ValidationError):
    code = 'customer_debt_row_limit'
    message_template = "Sheet '{raw_name}' exceeds the export limit of {max_rows} rows; narrow the filters"


class OrderLedgerRowLimitError(ValidationError):
    code = 'order_ledger_row_limit'
    message_template = 'The order ledger exceeds the export limit of {max_rows} rows; narrow the date range'


class ExportWorkbookRowLimitError(ValidationError):
    code = 'export_workbook_row_limit'
    message_template = 'The workbook exceeds the export limit of {max_rows} rows in total; use fewer sheets or narrower filters'


class TooManyFilterValuesError(ValidationError):
    code = 'too_many_filter_values'
    message_template = "'{name}' accepts at most {max_values} values"


class FilterValueTooLongError(ValidationError):
    code = 'filter_value_too_long'
    message_template = "Each '{name}' value must be at most {max_length} characters"


class CustomerNotFoundError(NotFoundError):
    code = 'customer_not_found'
    message_template = 'Customer not found'


class OrderNotFoundError(NotFoundError):
    code = 'order_not_found'
    message_template = 'Order not found'


class InvalidDebtHistoryDateRangeError(ValidationError):
    code = 'invalid_debt_history_date_range'
    message_template = 'date_from must be before or equal to date_to'


class DebtHistoryTooManyPointsError(ValidationError):
    code = 'debt_history_too_many_points'
    message_template = 'The balance series would have more than {max_points} points; choose a larger grain or a shorter range'


class DebtLedgerTooLargeError(ValidationError):
    code = 'debt_ledger_too_large'
    message_template = 'The customer ledger exceeds {max_entries} entries up to date_to; choose an earlier date_to'


class InvalidDebtHistoryCursorError(ValidationError):
    code = 'invalid_debt_history_cursor'
    message_template = 'Invalid debt history cursor'
