"""Central catalog of sales error codes and message templates."""
from src.common.errors import (
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
