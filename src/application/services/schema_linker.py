"""Link analyzed business entities to the PostgreSQL analytics schema."""

from dataclasses import dataclass, field

from src.domain.constants.query_intent import QueryIntent
from src.domain.entities.analyzed_query import AnalyzedQuery

_CUSTOMERS_SCHEMA = """\
Table: customers
Grain: one row per provisional canonical customer.
Columns:
    customer_id           UUID PRIMARY KEY
    customer_identity_key TEXT UNIQUE -- normalized name|ward|village
    customer_name         TEXT
    address_detail        TEXT
    village_name          TEXT
    ward_name             TEXT
    created_at            TIMESTAMPTZ
    updated_at            TIMESTAMPTZ
    deleted_at            TIMESTAMPTZ -- active row requires deleted_at IS NULL
"""

_SALES_INVOICES_SCHEMA = """\
Table: sales_invoices
Grain: one row per sales invoice.
Columns:
    invoice_id                       TEXT PRIMARY KEY -- internal UUID string
    invoice_number                   TEXT UNIQUE -- business invoice number, e.g. XB24169-0125
    issued_at                        TIMESTAMP -- transaction timestamp
    customer_id                      UUID REFERENCES customers.customer_id
    customer_name_snapshot           TEXT
    customer_address_detail_snapshot TEXT
    customer_village_name_snapshot   TEXT
    customer_ward_name_snapshot      TEXT
    invoice_total_amount             NUMERIC(18,2) -- gross sales before customer returns
    debt_delta_amount                NUMERIC(18,2) -- positive increases receivable; negative is advance/credit
    created_at                       TIMESTAMP
    deleted_at                       TIMESTAMP -- active row requires deleted_at IS NULL
"""

_SALES_INVOICE_LINES_SCHEMA = """\
Table: sales_invoice_lines
Grain: one row per line item within an invoice.
Columns:
    invoice_line_id      TEXT PRIMARY KEY
    invoice_id           TEXT REFERENCES sales_invoices.invoice_id
    line_number          INTEGER -- unique within invoice_id
    product_name         TEXT -- normalized product name
    product_category_name TEXT
    unit_name            TEXT
    unit_price           NUMERIC(18,2)
    quantity             NUMERIC(18,3)
    line_amount          NUMERIC(18,2) -- product/category-level revenue
    created_at           TIMESTAMP
    deleted_at           TIMESTAMP -- active row requires deleted_at IS NULL
"""

_CUSTOMER_DEBT_TRANSACTIONS_SCHEMA = """\
Table: customer_debt_transactions
Grain: one signed customer receivable movement from the source ledger.
Columns:
    debt_transaction_id TEXT PRIMARY KEY
    customer_id         UUID REFERENCES customers.customer_id
    source_type         TEXT -- opening, sale, receipt, sales_return
    source_id           TEXT -- unique together with source_type
    occurred_at         TIMESTAMP
    amount              NUMERIC(18,2) -- positive increases debt; negative decreases debt
    deleted_at          TIMESTAMPTZ -- active row requires deleted_at IS NULL
"""

_SALES_RETURNS_SCHEMA = """\
Table: sales_returns
Grain: one customer sales-return document (MDB reason NT).
Columns:
    return_id          TEXT PRIMARY KEY
    source_id          TEXT UNIQUE
    return_number      TEXT UNIQUE
    returned_at        TIMESTAMP
    customer_id        UUID REFERENCES customers.customer_id
    customer_name_snapshot TEXT
    return_total_amount NUMERIC(18,2) -- positive return-document total
    deleted_at         TIMESTAMPTZ

Table: sales_return_lines
Grain: one returned product line.
Columns:
    return_line_id      TEXT PRIMARY KEY
    return_id           TEXT REFERENCES sales_returns.return_id
    source_line_id      TEXT
    line_number         INTEGER
    product_name        TEXT
    product_category_name TEXT
    unit_name           TEXT
    unit_price          NUMERIC(18,2)
    quantity            NUMERIC(18,3) -- positive returned quantity
    line_amount         NUMERIC(18,2) -- positive returned value
    deleted_at          TIMESTAMPTZ
"""

_RELATIONSHIPS_AND_METRICS = """\
Relationships:
    customers.customer_id = sales_invoices.customer_id
    customers.customer_id = customer_debt_transactions.customer_id
    sales_invoices.invoice_id = sales_invoice_lines.invoice_id
    sales_returns.return_id = sales_return_lines.return_id
    customers.customer_id = sales_returns.customer_id

Mandatory metric rules:
    1. Net revenue overall/by customer/by ward/by time is gross sales minus returns:
       SUM(sales_invoices.invoice_total_amount) + SUM(customer_debt_transactions.amount)
       restricted to source_type = 'sales_return'. Return amounts are already negative.
       Aggregate sales and returns separately before combining them; join both to customers
       when grouping/filtering by customer or geography. Filter sales on issued_at and
       returns on occurred_at using the same closed-open date range.
    2. Net product/category revenue is sales line revenue minus returned line value.
       Aggregate sales_invoice_lines.line_amount by product/category/unit and subtract
       sales_return_lines.line_amount at the same grain. Filter sales by issued_at and
       returns by returned_at using the same date range.
    3. Net product quantity is SUM(sales_invoice_lines.quantity) minus
       SUM(sales_return_lines.quantity), grouped by product and unit_name.
    4. Never SUM invoice_total_amount after a direct one-to-many line join.
       Filter qualifying invoices with EXISTS or a DISTINCT invoice_id CTE.
    4. Group customer analytics by customers.customer_id and customers.customer_name,
       not by customer_name_snapshot alone.
    5. Filter product/category dates by joining lines to sales_invoices and applying
       predicates to sales_invoices.issued_at.
    6. Every referenced soft-deletable table must have alias.deleted_at IS NULL.
    7. PostgreSQL date examples:
       EXTRACT(YEAR FROM i.issued_at) = 2025
       EXTRACT(MONTH FROM i.issued_at) = 3
       EXTRACT(QUARTER FROM i.issued_at) = 1
       i.issued_at >= DATE '2025-03-01' AND i.issued_at < DATE '2025-04-01'
    8. Current customer debt is SUM(customer_debt_transactions.amount), never
       SUM(sales_invoices.debt_delta_amount). Filter debt dates on occurred_at.
    9. When customer_debt_transactions is used for revenue, include only active rows with
       source_type = 'sales_return'; do not include opening, sale, or receipt movements.
"""

_FULL_SCHEMA = "\n".join(
    (
        _CUSTOMERS_SCHEMA,
        _SALES_INVOICES_SCHEMA,
        _SALES_INVOICE_LINES_SCHEMA,
        _CUSTOMER_DEBT_TRANSACTIONS_SCHEMA,
        _SALES_RETURNS_SCHEMA,
        _RELATIONSHIPS_AND_METRICS,
    )
)


@dataclass
class LinkedSchema:
    primary_table: str
    filter_hints: dict = field(default_factory=dict)
    schema_context: str = ""
    entity_summary: str = ""


class SchemaLinker:
    """Map extracted entities to explicit tables, columns and metric grain."""

    _LINE_INTENTS = {QueryIntent.PRODUCT, QueryIntent.CATEGORY}

    def link(self, analyzed: AnalyzedQuery) -> LinkedSchema:
        hints: dict = {}
        entity_parts: list[str] = []

        tf = analyzed.time_filter
        if tf.year:
            hints["sales_invoices.issued_at.year"] = tf.year
            entity_parts.append(f"năm={tf.year}")
        if tf.month:
            hints["sales_invoices.issued_at.month"] = tf.month
            entity_parts.append(f"tháng={tf.month}")
        if tf.quarter:
            hints["sales_invoices.issued_at.quarter"] = tf.quarter
            entity_parts.append(f"quý={tf.quarter}")
        if tf.day:
            hints["sales_invoices.issued_at.day"] = tf.day
            entity_parts.append(f"ngày={tf.day}")

        if analyzed.customer_name:
            hints["customers.customer_name"] = analyzed.customer_name
            entity_parts.append(f"khách_hàng='{analyzed.customer_name}'")

        if analyzed.invoice_id:
            hints["sales_invoices.invoice_number"] = analyzed.invoice_id
            entity_parts.append(f"phiếu='{analyzed.invoice_id}'")

        if analyzed.category_names:
            hints["sales_invoice_lines.product_category_name.in"] = (
                analyzed.category_names
            )
            entity_parts.append(
                "danh_mục_trong=" + repr(analyzed.category_names)
            )
        elif analyzed.category_name:
            hints["sales_invoice_lines.product_category_name"] = analyzed.category_name
            entity_parts.append(f"danh_mục='{analyzed.category_name}'")

        if analyzed.top_n:
            hints["result_limit"] = min(analyzed.top_n, 1000)

        all_intents = set(analyzed.intents) | {analyzed.primary_intent}
        needs_lines = bool(
            analyzed.category_name
            or analyzed.category_names
            or all_intents & self._LINE_INTENTS
        )
        if needs_lines:
            primary_table = "sales_invoice_lines"
        elif analyzed.primary_intent == QueryIntent.CUSTOMER:
            primary_table = "customers"
        else:
            primary_table = "sales_invoices"

        return LinkedSchema(
            primary_table=primary_table,
            filter_hints=hints,
            schema_context=_FULL_SCHEMA,
            entity_summary=(
                ", ".join(entity_parts) if entity_parts else "không có bộ lọc cụ thể"
            ),
        )
