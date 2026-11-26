"""create the read-only role that LLM-generated SQL runs under

`sales_sql_reader` is a NOLOGIN role with USAGE on schema public and SELECT on
the six sales tables only. The role is granted to the user running the migration
(normally the application user) so `PostgresSQLExecutor` can `SET LOCAL ROLE`
inside its read-only transaction. PostgreSQL then refuses auth/conversation/ETL
tables and privileged functions even if the SQL validator misses something.

If the application connects as a different user than the one running Alembic,
grant the role manually:  GRANT sales_sql_reader TO <app_user>;

A table added to ALLOWED_SQL_TABLES needs a new migration that grants SELECT on
it and lists it in SQL_READER_TABLES (checked by tests/unit/test_sql_reader_role.py).

Revision ID: a91c3e7d5b20
Revises: 8008434c9371
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a91c3e7d5b20"
down_revision: Union[str, None] = "8008434c9371"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "sales_sql_reader"
# Frozen copy of ALLOWED_SQL_TABLES at the time of this migration.
SQL_READER_TABLES = (
    "customers",
    "sales_invoices",
    "sales_invoice_lines",
    "sales_returns",
    "sales_return_lines",
    "customer_debt_transactions",
)


def upgrade() -> None:
    tables = ", ".join(SQL_READER_TABLES)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT SELECT ON {tables} TO {ROLE}")
    op.execute(f"GRANT {ROLE} TO CURRENT_USER")


def downgrade() -> None:
    # Roles are cluster-wide: only drop it when no other database still grants it anything.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                EXECUTE 'DROP OWNED BY {ROLE}';
                BEGIN
                    EXECUTE 'DROP ROLE {ROLE}';
                EXCEPTION WHEN dependent_objects_still_exist THEN
                    RAISE NOTICE 'Role {ROLE} is still used by another database; kept it';
                END;
            END IF;
        END
        $$;
        """
    )
