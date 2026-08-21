"""normalize customer ward names across the database

Revision ID: f4a7b2c91d60
Revises: e8c1a4d92f30
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f4a7b2c91d60"
down_revision: Union[str, None] = "e8c1a4d92f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION pg_temp.normalize_customer_ward(value text)
        RETURNS text
        LANGUAGE SQL
        IMMUTABLE
        AS $$
            SELECT CASE
                WHEN value IS NULL OR btrim(value) = '' THEN NULL
                WHEN lower(btrim(value)) IN (
                    'thu hưng', 'thụy hưng', 'xã thụy hưng', 'thụy hựng', 'thuỵ hưng'
                ) THEN 'Thụy Hưng'
                WHEN lower(btrim(value)) IN (
                    'thụy việt', 'thụ việt', 'thuy việt', 'xã thụy việt',
                    'thụy vệt', 'thụy đồng'
                ) THEN 'Thụy Việt'
                WHEN lower(btrim(value)) IN (
                    'thụy ninh', 'xã thụy ninh', 'thuy ninh', 'thỵ ninh'
                ) THEN 'Thụy Ninh'
                WHEN lower(btrim(value)) = 'thụy sơn' THEN 'Thụy Sơn'
                WHEN lower(btrim(value)) IN (
                    'thụy phúc', 'thụỵ phúc', 'dương phúc'
                ) THEN 'Thụy Phúc'
                WHEN lower(btrim(value)) = 'thụy dân' THEN 'Thụy Dân'
                WHEN lower(btrim(value)) = 'thụy chính' THEN 'Thụy Chính'
                WHEN lower(btrim(value)) = 'thụy duyên' THEN 'Thụy Duyên'
                WHEN lower(btrim(value)) IN ('thụy văn', 'thụ văn') THEN 'Thụy Văn'
                WHEN lower(btrim(value)) = 'thụy phong' THEN 'Thụy Phong'
                WHEN lower(btrim(value)) = 'thụy quỳnh' THEN 'Thụy Quỳnh'
                WHEN lower(btrim(value)) = 'thụy liên' THEN 'Thụy Liên'
                WHEN lower(btrim(value)) = 'thụy hà' THEN 'Thụy Hà'
                WHEN lower(btrim(value)) IN (
                    'thụy dương', 'thụ dương', 'xã thụy dương'
                ) THEN 'Thụy Dương'
                WHEN lower(btrim(value)) = 'thái thịnh' THEN 'Thái Thịnh'
                WHEN lower(btrim(value)) = 'diêm điền' THEN 'Diêm Điền'
                WHEN lower(btrim(value)) = 'an mỹ' THEN 'An Mỹ'
                ELSE 'Khác'
            END
        $$
    """)

    op.execute("""
        CREATE TEMP TABLE customer_ward_merge ON COMMIT DROP AS
        WITH normalized AS (
            SELECT
                customer_id,
                deleted_at,
                pg_temp.normalize_customer_ward(ward_name) AS canonical_ward,
                concat_ws(
                    '|',
                    lower(regexp_replace(btrim(coalesce(customer_name, '')), '[[:space:]]+', ' ', 'g')),
                    lower(regexp_replace(btrim(coalesce(pg_temp.normalize_customer_ward(ward_name), '')), '[[:space:]]+', ' ', 'g')),
                    lower(regexp_replace(btrim(coalesce(village_name, '')), '[[:space:]]+', ' ', 'g'))
                ) AS new_identity_key
            FROM customers
        )
        SELECT
            customer_id,
            canonical_ward,
            new_identity_key,
            first_value(customer_id) OVER (
                PARTITION BY new_identity_key
                ORDER BY (deleted_at IS NULL) DESC, customer_id
            ) AS survivor_id
        FROM normalized
    """)
    op.execute("CREATE INDEX ON customer_ward_merge (customer_id)")
    op.execute("CREATE INDEX ON customer_ward_merge (survivor_id)")

    op.execute("""
        UPDATE sales_invoices AS invoice
        SET customer_id = mapping.survivor_id
        FROM customer_ward_merge AS mapping
        WHERE invoice.customer_id = mapping.customer_id
          AND mapping.customer_id <> mapping.survivor_id
    """)
    op.execute("""
        UPDATE customer_debt_transactions AS debt
        SET customer_id = mapping.survivor_id,
            updated_at = CURRENT_TIMESTAMP
        FROM customer_ward_merge AS mapping
        WHERE debt.customer_id = mapping.customer_id
          AND mapping.customer_id <> mapping.survivor_id
    """)
    op.execute("""
        DELETE FROM customers AS customer
        USING customer_ward_merge AS mapping
        WHERE customer.customer_id = mapping.customer_id
          AND mapping.customer_id <> mapping.survivor_id
    """)
    op.execute("""
        UPDATE customers AS customer
        SET ward_name = mapping.canonical_ward,
            customer_identity_key = mapping.new_identity_key,
            updated_at = CURRENT_TIMESTAMP
        FROM customer_ward_merge AS mapping
        WHERE customer.customer_id = mapping.survivor_id
          AND mapping.customer_id = mapping.survivor_id
    """)
    op.execute("""
        UPDATE sales_invoices
        SET customer_ward_name_snapshot =
            pg_temp.normalize_customer_ward(customer_ward_name_snapshot)
    """)


def downgrade() -> None:
    # Canonicalization and duplicate merges are intentionally irreversible.
    pass
