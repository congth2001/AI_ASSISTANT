"""infer customer wards and villages from full address text

Revision ID: a93d7c5e124b
Revises: f4a7b2c91d60
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a93d7c5e124b"
down_revision: Union[str, None] = "f4a7b2c91d60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TEMP TABLE customer_ward_aliases (
            alias text PRIMARY KEY,
            canonical_ward text NOT NULL
        ) ON COMMIT DROP
    """)
    op.execute("""
        INSERT INTO customer_ward_aliases (alias, canonical_ward) VALUES
            ('Thu Hưng', 'Thụy Hưng'),
            ('Thụy Hưng', 'Thụy Hưng'),
            ('Xã Thụy Hưng', 'Thụy Hưng'),
            ('Thụy Hựng', 'Thụy Hưng'),
            ('Thuỵ Hưng', 'Thụy Hưng'),
            ('Thụy Việt', 'Thụy Việt'),
            ('Thụ Việt', 'Thụy Việt'),
            ('Thuy Việt', 'Thụy Việt'),
            ('Xã Thụy Việt', 'Thụy Việt'),
            ('Thụy Vệt', 'Thụy Việt'),
            ('Thụy Đồng', 'Thụy Việt'),
            ('Thụy Ninh', 'Thụy Ninh'),
            ('Xã Thụy Ninh', 'Thụy Ninh'),
            ('Thuy Ninh', 'Thụy Ninh'),
            ('Thỵ Ninh', 'Thụy Ninh'),
            ('Thụy Sơn', 'Thụy Sơn'),
            ('Thụy Phúc', 'Thụy Phúc'),
            ('Thụỵ Phúc', 'Thụy Phúc'),
            ('Dương Phúc', 'Thụy Phúc'),
            ('Thụy Dân', 'Thụy Dân'),
            ('Thụy Chính', 'Thụy Chính'),
            ('Thụy Duyên', 'Thụy Duyên'),
            ('Thụy Văn', 'Thụy Văn'),
            ('Thụ Văn', 'Thụy Văn'),
            ('Thụy Phong', 'Thụy Phong'),
            ('Thụy Quỳnh', 'Thụy Quỳnh'),
            ('Thụy Liên', 'Thụy Liên'),
            ('Thụy Hà', 'Thụy Hà'),
            ('Thụy Dương', 'Thụy Dương'),
            ('Thụ Dương', 'Thụy Dương'),
            ('Xã Thụy Dương', 'Thụy Dương'),
            ('Thái Thịnh', 'Thái Thịnh'),
            ('Diêm Điền', 'Diêm Điền'),
            ('An Mỹ', 'An Mỹ')
    """)

    op.execute("""
        CREATE TEMP TABLE customer_location_merge ON COMMIT DROP AS
        WITH inferred AS (
            SELECT
                customer.customer_id,
                customer.deleted_at,
                CASE
                    WHEN nullif(btrim(customer.address_detail), '') IS NULL THEN NULL
                    WHEN matched.alias IS NULL THEN 'Khác'
                    ELSE matched.canonical_ward
                END AS canonical_ward,
                CASE
                    WHEN nullif(btrim(customer.address_detail), '') IS NULL THEN NULL
                    WHEN matched.alias IS NULL THEN btrim(customer.address_detail)
                    ELSE nullif(
                        btrim(
                            regexp_replace(
                                customer.address_detail,
                                matched.alias,
                                ' ',
                                'i'
                            ),
                            E' \\t\\n\\r_-,;'
                        ),
                        ''
                    )
                END AS canonical_village,
                customer.customer_name
            FROM customers AS customer
            LEFT JOIN LATERAL (
                SELECT aliases.alias, aliases.canonical_ward
                FROM customer_ward_aliases AS aliases
                WHERE strpos(lower(customer.address_detail), lower(aliases.alias)) > 0
                ORDER BY length(aliases.alias) DESC
                LIMIT 1
            ) AS matched ON true
        ), keyed AS (
            SELECT
                *,
                concat_ws(
                    '|',
                    lower(regexp_replace(btrim(coalesce(customer_name, '')), '[[:space:]]+', ' ', 'g')),
                    lower(regexp_replace(btrim(coalesce(canonical_ward, '')), '[[:space:]]+', ' ', 'g')),
                    lower(regexp_replace(btrim(coalesce(canonical_village, '')), '[[:space:]]+', ' ', 'g'))
                ) AS new_identity_key
            FROM inferred
        )
        SELECT
            customer_id,
            canonical_ward,
            canonical_village,
            new_identity_key,
            first_value(customer_id) OVER (
                PARTITION BY new_identity_key
                ORDER BY (deleted_at IS NULL) DESC, customer_id
            ) AS survivor_id
        FROM keyed
    """)
    op.execute("CREATE INDEX ON customer_location_merge (customer_id)")
    op.execute("CREATE INDEX ON customer_location_merge (survivor_id)")

    op.execute("""
        UPDATE sales_invoices AS invoice
        SET customer_id = mapping.survivor_id
        FROM customer_location_merge AS mapping
        WHERE invoice.customer_id = mapping.customer_id
          AND mapping.customer_id <> mapping.survivor_id
    """)
    op.execute("""
        UPDATE customer_debt_transactions AS debt
        SET customer_id = mapping.survivor_id,
            updated_at = CURRENT_TIMESTAMP
        FROM customer_location_merge AS mapping
        WHERE debt.customer_id = mapping.customer_id
          AND mapping.customer_id <> mapping.survivor_id
    """)
    op.execute("""
        DELETE FROM customers AS customer
        USING customer_location_merge AS mapping
        WHERE customer.customer_id = mapping.customer_id
          AND mapping.customer_id <> mapping.survivor_id
    """)
    op.execute("""
        UPDATE customers AS customer
        SET ward_name = mapping.canonical_ward,
            village_name = mapping.canonical_village,
            customer_identity_key = mapping.new_identity_key,
            updated_at = CURRENT_TIMESTAMP
        FROM customer_location_merge AS mapping
        WHERE customer.customer_id = mapping.survivor_id
          AND mapping.customer_id = mapping.survivor_id
    """)

    op.execute("""
        WITH matched AS (
            SELECT
                invoice.invoice_id,
                location.alias,
                location.canonical_ward
            FROM sales_invoices AS invoice
            CROSS JOIN LATERAL (
                SELECT aliases.alias, aliases.canonical_ward
                FROM customer_ward_aliases AS aliases
                WHERE strpos(
                    lower(invoice.customer_address_detail_snapshot),
                    lower(aliases.alias)
                ) > 0
                ORDER BY length(aliases.alias) DESC
                LIMIT 1
            ) AS location
        )
        UPDATE sales_invoices AS invoice
        SET customer_ward_name_snapshot = matched.canonical_ward,
            customer_village_name_snapshot = nullif(
                btrim(
                    regexp_replace(
                        invoice.customer_address_detail_snapshot,
                        matched.alias,
                        ' ',
                        'i'
                    ),
                    E' \\t\\n\\r_-,;'
                ),
                ''
            )
        FROM matched
        WHERE invoice.invoice_id = matched.invoice_id
    """)
    op.execute("""
        UPDATE sales_invoices
        SET customer_ward_name_snapshot = CASE
                WHEN nullif(btrim(customer_address_detail_snapshot), '') IS NULL THEN NULL
                ELSE 'Khác'
            END,
            customer_village_name_snapshot = nullif(
                btrim(customer_address_detail_snapshot),
                ''
            )
        WHERE NOT EXISTS (
            SELECT 1
            FROM customer_ward_aliases AS aliases
            WHERE strpos(
                lower(sales_invoices.customer_address_detail_snapshot),
                lower(aliases.alias)
            ) > 0
        )
    """)


def downgrade() -> None:
    # Address inference and duplicate customer merges are intentionally irreversible.
    pass
