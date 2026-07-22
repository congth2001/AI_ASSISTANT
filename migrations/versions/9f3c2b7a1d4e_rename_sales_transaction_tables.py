"""normalize customers and make sales transaction grain explicit

Revision ID: 9f3c2b7a1d4e
Revises: 46b1a595761c
Create Date: 2026-07-19 00:00:00.000000

This migration preserves the existing invoice and line-item rows.  In
particular, it assigns a deterministic line_number inside every invoice
instead of attempting to remove identical-looking source rows.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9f3c2b7a1d4e"
down_revision: Union[str, None] = "46b1a595761c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The old child table references the business invoice number. Drop that
    # relationship before renaming the tables and replace it with a PK-based FK.
    op.drop_constraint(
        "invoice_goods_invoice_customers_fk",
        "invoice_goods",
        type_="foreignkey",
    )

    op.rename_table("invoice_customers", "sales_invoices")
    op.rename_table("invoice_goods", "sales_invoice_lines")
    op.execute(
        "ALTER TABLE sales_invoices "
        "RENAME CONSTRAINT invoice_customers_pkey TO sales_invoices_pkey"
    )
    op.execute(
        "ALTER TABLE sales_invoice_lines "
        "RENAME CONSTRAINT invoice_goods_pkey TO sales_invoice_lines_pkey"
    )

    # Keep the existing UUID/string identifiers. Only make their role explicit.
    op.alter_column("sales_invoices", "invoice_id", new_column_name="invoice_number")
    op.alter_column("sales_invoices", "id", new_column_name="invoice_id")
    op.alter_column("sales_invoices", "date", new_column_name="issued_at")
    op.alter_column(
        "sales_invoices",
        "name",
        new_column_name="customer_name_snapshot",
    )
    op.alter_column(
        "sales_invoices",
        "address_detail",
        new_column_name="customer_address_detail_snapshot",
    )
    op.alter_column(
        "sales_invoices",
        "address_village",
        new_column_name="customer_village_name_snapshot",
    )
    op.alter_column(
        "sales_invoices",
        "address_ward",
        new_column_name="customer_ward_name_snapshot",
    )
    op.alter_column(
        "sales_invoices",
        "total_amount",
        new_column_name="invoice_total_amount",
    )
    op.alter_column(
        "sales_invoices",
        "debt_amount",
        new_column_name="debt_delta_amount",
    )

    op.alter_column("sales_invoice_lines", "id", new_column_name="invoice_line_id")
    op.alter_column(
        "sales_invoice_lines",
        "invoice_id",
        new_column_name="legacy_invoice_number",
    )
    op.alter_column("sales_invoice_lines", "name", new_column_name="product_name")
    op.alter_column(
        "sales_invoice_lines",
        "category",
        new_column_name="product_category_name",
    )
    op.alter_column("sales_invoice_lines", "unit_type", new_column_name="unit_name")
    op.alter_column("sales_invoice_lines", "total_price", new_column_name="line_amount")

    # PostgreSQL retains the old index name when a table/column is renamed.
    op.execute(
        "ALTER INDEX IF EXISTS invoice_customers_invoice_id_idx "
        "RENAME TO ux_sales_invoices_invoice_number"
    )

    # Money must use exact decimal arithmetic. Quantity keeps three decimal
    # places, matching the precision documented by the source dataset.
    op.alter_column(
        "sales_invoices",
        "invoice_total_amount",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 2),
        postgresql_using="ROUND(invoice_total_amount::numeric, 2)",
        existing_nullable=False,
    )
    op.alter_column(
        "sales_invoices",
        "debt_delta_amount",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 2),
        postgresql_using="ROUND(debt_delta_amount::numeric, 2)",
        existing_nullable=True,
    )
    op.alter_column(
        "sales_invoice_lines",
        "unit_price",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 2),
        postgresql_using="ROUND(unit_price::numeric, 2)",
        existing_nullable=False,
    )
    op.alter_column(
        "sales_invoice_lines",
        "quantity",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 3),
        postgresql_using="ROUND(quantity::numeric, 3)",
        existing_nullable=False,
    )
    op.alter_column(
        "sales_invoice_lines",
        "line_amount",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 2),
        postgresql_using="ROUND(line_amount::numeric, 2)",
        existing_nullable=False,
    )

    # A UUID is the stable technical identity of a customer. The source has no
    # customer code, so customer_identity_key is a provisional natural key
    # derived from normalized name + ward + village. Invoice snapshots are kept
    # unchanged so historical documents remain auditable.
    op.create_table(
        "customers",
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("customer_identity_key", sa.Text(), nullable=False),
        sa.Column("customer_name", sa.Text(), nullable=False),
        sa.Column("address_detail", sa.Text(), nullable=True),
        sa.Column("village_name", sa.String(), nullable=True),
        sa.Column("ward_name", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("customer_id", name="customers_pkey"),
        sa.UniqueConstraint(
            "customer_identity_key",
            name="uq_customers_customer_identity_key",
        ),
    )

    op.execute("""
        WITH normalized_invoices AS (
            SELECT
                invoice_id,
                issued_at,
                customer_name_snapshot,
                customer_address_detail_snapshot,
                customer_village_name_snapshot,
                customer_ward_name_snapshot,
                concat_ws(
                    '|',
                    lower(regexp_replace(
                        btrim(coalesce(customer_name_snapshot, '')),
                        '[[:space:]]+', ' ', 'g'
                    )),
                    lower(regexp_replace(
                        btrim(coalesce(customer_ward_name_snapshot, '')),
                        '[[:space:]]+', ' ', 'g'
                    )),
                    lower(regexp_replace(
                        btrim(coalesce(customer_village_name_snapshot, '')),
                        '[[:space:]]+', ' ', 'g'
                    ))
                ) AS customer_identity_key
            FROM sales_invoices
        ),
        latest_customer_snapshot AS (
            SELECT DISTINCT ON (customer_identity_key)
                customer_identity_key,
                customer_name_snapshot,
                customer_address_detail_snapshot,
                customer_village_name_snapshot,
                customer_ward_name_snapshot
            FROM normalized_invoices
            ORDER BY customer_identity_key, issued_at DESC, invoice_id
        )
        INSERT INTO customers (
            customer_identity_key,
            customer_name,
            address_detail,
            village_name,
            ward_name
        )
        SELECT
            customer_identity_key,
            customer_name_snapshot,
            customer_address_detail_snapshot,
            customer_village_name_snapshot,
            customer_ward_name_snapshot
        FROM latest_customer_snapshot
        """)

    op.add_column(
        "sales_invoices",
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.execute("""
        UPDATE sales_invoices AS invoice
        SET customer_id = customer.customer_id
        FROM customers AS customer
        WHERE customer.customer_identity_key = concat_ws(
            '|',
            lower(regexp_replace(
                btrim(coalesce(invoice.customer_name_snapshot, '')),
                '[[:space:]]+', ' ', 'g'
            )),
            lower(regexp_replace(
                btrim(coalesce(invoice.customer_ward_name_snapshot, '')),
                '[[:space:]]+', ' ', 'g'
            )),
            lower(regexp_replace(
                btrim(coalesce(invoice.customer_village_name_snapshot, '')),
                '[[:space:]]+', ' ', 'g'
            ))
        )
        """)
    op.alter_column(
        "sales_invoices",
        "customer_id",
        existing_type=postgresql.UUID(as_uuid=False),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_sales_invoices_customer_id",
        "sales_invoices",
        "customers",
        ["customer_id"],
        ["customer_id"],
        ondelete="RESTRICT",
    )

    # Link lines to the invoice primary key while the legacy invoice number is
    # still available for the data backfill.
    op.add_column(
        "sales_invoice_lines",
        sa.Column("invoice_id", sa.String(), nullable=True),
    )
    op.add_column(
        "sales_invoice_lines",
        sa.Column("line_number", sa.Integer(), nullable=True),
    )

    op.execute("""
        UPDATE sales_invoice_lines AS line
        SET invoice_id = invoice.invoice_id
        FROM sales_invoices AS invoice
        WHERE invoice.invoice_number = line.legacy_invoice_number
        """)

    # Preserve every source row, including identical-looking rows. The UUID is
    # used as the final ordering key so the backfill is deterministic.
    op.execute("""
        WITH numbered_lines AS (
            SELECT
                invoice_line_id,
                ROW_NUMBER() OVER (
                    PARTITION BY invoice_id
                    ORDER BY created_at NULLS LAST, invoice_line_id
                )::integer AS generated_line_number
            FROM sales_invoice_lines
        )
        UPDATE sales_invoice_lines AS line
        SET line_number = numbered.generated_line_number
        FROM numbered_lines AS numbered
        WHERE numbered.invoice_line_id = line.invoice_line_id
        """)

    # These NOT NULL operations intentionally fail the migration if the live DB
    # contains an orphan line, rather than silently dropping or mislinking data.
    op.alter_column(
        "sales_invoice_lines",
        "invoice_id",
        existing_type=sa.String(),
        nullable=False,
    )
    op.alter_column(
        "sales_invoice_lines",
        "line_number",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.create_foreign_key(
        "fk_sales_invoice_lines_invoice_id",
        "sales_invoice_lines",
        "sales_invoices",
        ["invoice_id"],
        ["invoice_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_sales_invoice_lines_invoice_line",
        "sales_invoice_lines",
        ["invoice_id", "line_number"],
    )

    op.drop_column("sales_invoice_lines", "legacy_invoice_number")

    op.create_check_constraint(
        "ck_sales_invoices_total_nonnegative",
        "sales_invoices",
        "invoice_total_amount >= 0",
    )
    op.create_check_constraint(
        "ck_sales_invoice_lines_line_number_positive",
        "sales_invoice_lines",
        "line_number > 0",
    )
    op.create_check_constraint(
        "ck_sales_invoice_lines_quantity_nonnegative",
        "sales_invoice_lines",
        "quantity >= 0",
    )
    op.create_check_constraint(
        "ck_sales_invoice_lines_unit_price_nonnegative",
        "sales_invoice_lines",
        "unit_price >= 0",
    )
    op.create_check_constraint(
        "ck_sales_invoice_lines_amount_nonnegative",
        "sales_invoice_lines",
        "line_amount >= 0",
    )

    op.create_index(
        "ix_sales_invoices_issued_at",
        "sales_invoices",
        ["issued_at"],
    )
    op.create_index(
        "ix_sales_invoices_customer_id",
        "sales_invoices",
        ["customer_id"],
    )
    op.create_index(
        "ix_customers_customer_name",
        "customers",
        ["customer_name"],
    )
    op.create_index(
        "ix_sales_invoice_lines_invoice_id",
        "sales_invoice_lines",
        ["invoice_id"],
    )
    op.create_index(
        "ix_sales_invoice_lines_product_name",
        "sales_invoice_lines",
        ["product_name"],
    )
    op.create_index(
        "ix_sales_invoice_lines_product_category_name",
        "sales_invoice_lines",
        ["product_category_name"],
    )

    # These comments are part of the semantic contract for schema introspection
    # and Text-to-SQL agents.
    op.execute("""
        COMMENT ON TABLE customers IS
        'Grain: one row per provisional customer identity. customer_id is the stable UUID; customer_identity_key is normalized name + ward + village until a source customer code exists.'
        """)
    op.execute("""
        COMMENT ON TABLE sales_invoices IS
        'Grain: one row per sales invoice. Join customers by customer_id; snapshot columns preserve the customer text printed on the historical invoice.'
        """)
    op.execute("""
        COMMENT ON TABLE sales_invoice_lines IS
        'Grain: one row per line item within a sales invoice. Use line_amount for product/category revenue.'
        """)
    op.execute("""
        COMMENT ON COLUMN sales_invoices.customer_id IS
        'Stable UUID foreign key to customers; use this column instead of grouping by customer_name_snapshot.'
        """)
    op.execute("""
        COMMENT ON COLUMN sales_invoices.invoice_total_amount IS
        'Authoritative invoice-level total; it is not guaranteed to equal SUM(sales_invoice_lines.line_amount) until source reconciliation is complete.'
        """)
    op.execute("""
        COMMENT ON COLUMN sales_invoices.debt_delta_amount IS
        'Signed debt movement recorded by this invoice: positive increases receivable, negative represents advance/credit.'
        """)
    op.execute("""
        COMMENT ON COLUMN sales_invoice_lines.line_number IS
        'Stable ordinal of the source line within its invoice; unique together with invoice_id.'
        """)


def downgrade() -> None:
    # Restore the business invoice number on every line before removing the
    # PK-based relationship.
    op.add_column(
        "sales_invoice_lines",
        sa.Column("legacy_invoice_number", sa.String(), nullable=True),
    )
    op.execute("""
        UPDATE sales_invoice_lines AS line
        SET legacy_invoice_number = invoice.invoice_number
        FROM sales_invoices AS invoice
        WHERE invoice.invoice_id = line.invoice_id
        """)
    op.alter_column(
        "sales_invoice_lines",
        "legacy_invoice_number",
        existing_type=sa.String(),
        nullable=False,
    )

    op.drop_index(
        "ix_sales_invoice_lines_product_category_name",
        table_name="sales_invoice_lines",
    )
    op.drop_index(
        "ix_sales_invoice_lines_product_name",
        table_name="sales_invoice_lines",
    )
    op.drop_index(
        "ix_sales_invoice_lines_invoice_id",
        table_name="sales_invoice_lines",
    )
    op.drop_index(
        "ix_customers_customer_name",
        table_name="customers",
    )
    op.drop_index(
        "ix_sales_invoices_customer_id",
        table_name="sales_invoices",
    )
    op.drop_index(
        "ix_sales_invoices_issued_at",
        table_name="sales_invoices",
    )

    op.drop_constraint(
        "ck_sales_invoice_lines_amount_nonnegative",
        "sales_invoice_lines",
        type_="check",
    )
    op.drop_constraint(
        "ck_sales_invoice_lines_unit_price_nonnegative",
        "sales_invoice_lines",
        type_="check",
    )
    op.drop_constraint(
        "ck_sales_invoice_lines_quantity_nonnegative",
        "sales_invoice_lines",
        type_="check",
    )
    op.drop_constraint(
        "ck_sales_invoice_lines_line_number_positive",
        "sales_invoice_lines",
        type_="check",
    )
    op.drop_constraint(
        "ck_sales_invoices_total_nonnegative",
        "sales_invoices",
        type_="check",
    )
    op.drop_constraint(
        "uq_sales_invoice_lines_invoice_line",
        "sales_invoice_lines",
        type_="unique",
    )
    op.drop_constraint(
        "fk_sales_invoice_lines_invoice_id",
        "sales_invoice_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_sales_invoices_customer_id",
        "sales_invoices",
        type_="foreignkey",
    )

    op.drop_column("sales_invoice_lines", "line_number")
    op.drop_column("sales_invoice_lines", "invoice_id")
    op.drop_column("sales_invoices", "customer_id")
    op.drop_table("customers")

    op.alter_column(
        "sales_invoice_lines",
        "line_amount",
        existing_type=sa.Numeric(18, 2),
        type_=sa.Float(),
        postgresql_using="line_amount::double precision",
        existing_nullable=False,
    )
    op.alter_column(
        "sales_invoice_lines",
        "quantity",
        existing_type=sa.Numeric(18, 3),
        type_=sa.Float(),
        postgresql_using="quantity::double precision",
        existing_nullable=False,
    )
    op.alter_column(
        "sales_invoice_lines",
        "unit_price",
        existing_type=sa.Numeric(18, 2),
        type_=sa.Float(),
        postgresql_using="unit_price::double precision",
        existing_nullable=False,
    )
    op.alter_column(
        "sales_invoices",
        "debt_delta_amount",
        existing_type=sa.Numeric(18, 2),
        type_=sa.Float(),
        postgresql_using="debt_delta_amount::double precision",
        existing_nullable=True,
    )
    op.alter_column(
        "sales_invoices",
        "invoice_total_amount",
        existing_type=sa.Numeric(18, 2),
        type_=sa.Float(),
        postgresql_using="invoice_total_amount::double precision",
        existing_nullable=False,
    )

    op.alter_column(
        "sales_invoice_lines",
        "invoice_line_id",
        new_column_name="id",
    )
    op.alter_column(
        "sales_invoice_lines",
        "legacy_invoice_number",
        new_column_name="invoice_id",
    )
    op.alter_column("sales_invoice_lines", "product_name", new_column_name="name")
    op.alter_column(
        "sales_invoice_lines",
        "product_category_name",
        new_column_name="category",
    )
    op.alter_column("sales_invoice_lines", "unit_name", new_column_name="unit_type")
    op.alter_column("sales_invoice_lines", "line_amount", new_column_name="total_price")

    op.alter_column("sales_invoices", "invoice_id", new_column_name="id")
    op.alter_column("sales_invoices", "invoice_number", new_column_name="invoice_id")
    op.alter_column("sales_invoices", "issued_at", new_column_name="date")
    op.alter_column(
        "sales_invoices",
        "customer_name_snapshot",
        new_column_name="name",
    )
    op.alter_column(
        "sales_invoices",
        "customer_address_detail_snapshot",
        new_column_name="address_detail",
    )
    op.alter_column(
        "sales_invoices",
        "customer_village_name_snapshot",
        new_column_name="address_village",
    )
    op.alter_column(
        "sales_invoices",
        "customer_ward_name_snapshot",
        new_column_name="address_ward",
    )
    op.alter_column(
        "sales_invoices",
        "invoice_total_amount",
        new_column_name="total_amount",
    )
    op.alter_column(
        "sales_invoices", "debt_delta_amount", new_column_name="debt_amount"
    )

    op.execute(
        "ALTER TABLE sales_invoice_lines "
        "RENAME CONSTRAINT sales_invoice_lines_pkey TO invoice_goods_pkey"
    )
    op.execute(
        "ALTER TABLE sales_invoices "
        "RENAME CONSTRAINT sales_invoices_pkey TO invoice_customers_pkey"
    )
    op.rename_table("sales_invoice_lines", "invoice_goods")
    op.rename_table("sales_invoices", "invoice_customers")

    op.execute(
        "ALTER INDEX IF EXISTS ux_sales_invoices_invoice_number "
        "RENAME TO invoice_customers_invoice_id_idx"
    )

    op.create_foreign_key(
        "invoice_goods_invoice_customers_fk",
        "invoice_goods",
        "invoice_customers",
        ["invoice_id"],
        ["invoice_id"],
    )
