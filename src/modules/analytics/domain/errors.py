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
    message_template = "Sheet '{raw_name}' exceeds the Excel row limit"


class OrderLedgerRowLimitError(ValidationError):
    code = 'order_ledger_row_limit'
    message_template = 'The order ledger exceeds the Excel row limit'


class CustomerNotFoundError(NotFoundError):
    code = 'customer_not_found'
    message_template = 'Customer not found'


class OrderNotFoundError(NotFoundError):
    code = 'order_not_found'
    message_template = 'Order not found'
