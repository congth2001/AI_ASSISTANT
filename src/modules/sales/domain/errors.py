"""Central catalog of sales error codes and message templates."""
from src.common.errors import (
    ConflictError,
    ConfigurationError,
    InternalError,
    ValidationError,
)


class InconsistentSalesReturnHeadersError(ValidationError):
    code = 'inconsistent_sales_return_headers'
    message_template = 'Sales return snapshot has inconsistent duplicate headers'


class DuplicateSalesReturnLinesError(ValidationError):
    code = 'duplicate_sales_return_lines'
    message_template = 'Sales return snapshot contains duplicate source lines'


class UnknownSalesReturnHeadersError(ValidationError):
    code = 'unknown_sales_return_headers'
    message_template = 'Sales return lines reference unknown headers: {header_ids}'


class DuplicateDebtTransactionsError(ValidationError):
    code = 'duplicate_debt_transactions'
    message_template = 'Debt snapshot contains duplicate source keys'


class DuplicateInvoiceNumbersError(ValidationError):
    code = 'duplicate_invoice_numbers'
    message_template = 'Customer snapshot contains duplicate invoice numbers: {invoice_numbers}'


class IncompleteInvoiceUpsertError(InternalError):
    code = 'incomplete_invoice_upsert'
    message_template = 'Invoice upsert did not return an ID for every invoice'


class UnknownInvoiceReferencesError(ValidationError):
    code = 'unknown_invoice_references'
    message_template = 'Goods snapshot references invoices that do not exist: {invoice_numbers}'


class RequiredColumnValueError(ValidationError):
    code = 'required_column_value'
    message_template = 'Column {column!r} contains an empty value'


class MissingSnapshotColumnsError(ValidationError):
    code = 'missing_snapshot_columns'
    message_template = '{snapshot_name} snapshot is missing columns: {columns}'


class DebtRepositoryRequiredError(ConfigurationError):
    code = 'debt_repository_required'
    message_template = 'Customer debt transaction repository is not configured'


class SalesReturnRepositoryRequiredError(ConfigurationError):
    code = 'sales_return_repository_required'
    message_template = 'Sales return repository is not configured'


class SalesReturnLinesRequiredError(ValidationError):
    code = 'sales_return_lines_required'
    message_template = 'Sales return lines snapshot is required'


class InvoiceIssueDateRequiredError(ValidationError):
    code = 'invoice_issue_date_required'
    message_template = 'Invoice {invoice_number} has no issue date'


class CustomerIdentityMissingError(InternalError):
    code = 'customer_identity_missing'
    message_template = 'Customer upsert returned no UUID for {identity_key!r}'


class DuplicateSalesReturnNumbersError(ValidationError):
    code = 'duplicate_sales_return_numbers'
    message_template = 'Sales return snapshot contains duplicate return numbers: {return_numbers}'


class InvalidDecimalValueError(ValidationError):
    code = 'invalid_decimal_value'
    message_template = 'Column {column!r} contains a value that is not a finite number in range: {value!r}'


class InvalidDatetimeValueError(ValidationError):
    code = 'invalid_datetime_value'
    message_template = 'Column {column!r} contains an invalid date/time: {value!r}'


class EmptySnapshotError(ConflictError):
    code = 'empty_snapshot'
    message_template = (
        '{snapshot_name} snapshot is empty but {active_count} active records exist; '
        'refusing to soft-delete them (pass allow_shrink=True / --allow-shrink to override)'
    )


class SnapshotShrinkError(ConflictError):
    code = 'snapshot_shrink'
    message_template = (
        '{snapshot_name} snapshot has {snapshot_count} records versus {active_count} active '
        '(drop above {threshold_percent}%); refusing to soft-delete the difference '
        '(pass allow_shrink=True / --allow-shrink to override)'
    )


class InvalidDebtSourceTypeError(ValidationError):
    code = 'invalid_debt_source_type'
    message_template = 'Debt snapshot contains unsupported source_type: {source_type!r}'
