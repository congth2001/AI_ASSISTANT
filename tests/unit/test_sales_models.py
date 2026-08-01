from decimal import Decimal

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import UUID

from src.infrastructure.repositories.models import (
    Customer,
    SalesInvoice,
    SalesInvoiceLine,
)
from src.infrastructure.repositories.repository_utils import to_decimal


def test_sales_model_table_names_and_grain_columns():
    assert Customer.__tablename__ == "customers"
    assert SalesInvoice.__tablename__ == "sales_invoices"
    assert SalesInvoiceLine.__tablename__ == "sales_invoice_lines"

    assert "customer_id" in SalesInvoice.__table__.columns
    assert "customer_name_snapshot" in SalesInvoice.__table__.columns
    assert "line_number" in SalesInvoiceLine.__table__.columns
    assert "product_name" in SalesInvoiceLine.__table__.columns


def test_customer_and_money_types_match_migration():
    assert isinstance(Customer.__table__.c.customer_id.type, UUID)
    assert isinstance(SalesInvoice.__table__.c.customer_id.type, UUID)

    invoice_total_type = SalesInvoice.__table__.c.invoice_total_amount.type
    line_amount_type = SalesInvoiceLine.__table__.c.line_amount.type
    quantity_type = SalesInvoiceLine.__table__.c.quantity.type

    assert isinstance(invoice_total_type, Numeric)
    assert (invoice_total_type.precision, invoice_total_type.scale) == (18, 2)
    assert (line_amount_type.precision, line_amount_type.scale) == (18, 2)
    assert (quantity_type.precision, quantity_type.scale) == (18, 3)


def test_sales_foreign_keys_target_primary_entities():
    invoice_customer_fk = next(iter(SalesInvoice.__table__.c.customer_id.foreign_keys))
    line_invoice_fk = next(iter(SalesInvoiceLine.__table__.c.invoice_id.foreign_keys))

    assert invoice_customer_fk.target_fullname == "customers.customer_id"
    assert line_invoice_fk.target_fullname == "sales_invoices.invoice_id"


def test_decimal_conversion_does_not_keep_binary_float_artifacts():
    assert to_decimal(0.1) == Decimal("0.1")
