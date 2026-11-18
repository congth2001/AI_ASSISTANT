"""Generated SQL may only read sales tables, whatever the LLM is talked into."""
import pytest

from src.bootstrap.orm import Base
from src.modules.assistant.application.services.sql_service import (
    ALLOWED_SQL_TABLES,
    RESTRICTED_SQL_TABLES,
    SQLService,
)
from src.modules.assistant.application.prompts.sql_prompts import SQLPrompt
from src.modules.assistant.domain.errors import SQLTableNotAllowedError


def validate(sql: str) -> str:
    return SQLService(llm_service=None).validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT u.email, u.password_hash FROM users u",
        "SELECT c.customer_name FROM customers c JOIN users u ON u.id = c.customer_id",
        "SELECT i.invoice_id FROM sales_invoices i, users u",
        "SELECT i.invoice_id FROM sales_invoices AS i, public.users AS u",
        'SELECT x.id FROM "Users" x',
        'SELECT x.id FROM public."users" x',
        "SELECT t.token_id FROM refresh_tokens t",
        "SELECT m.content FROM messages m",
        "SELECT c.title FROM conversations c",
        "SELECT a.version_num FROM alembic_version a",
        "SELECT i.invoice_id FROM sales_invoices i WHERE EXISTS (SELECT 1 FROM users u)",
        "SELECT (SELECT u.email FROM users u LIMIT 1) AS e FROM customers c",
        "WITH users AS (SELECT u.password_hash FROM users u) SELECT x.password_hash FROM users x",
        "WITH a AS (SELECT 1 AS n) SELECT s.n FROM (SELECT 1 AS n) s, users u",
        "SELECT x.n FROM other_schema.customers x",
        "SELECT x.n FROM some_unknown_table x",
        "SELECT x.n FROM LATERAL some_unknown_table x",
        "SELECT x.n FROM dblink('host=x', 'SELECT 1') AS x(n int)",
        "SELECT x.n FROM (TABLE users) x",
        "SELECT $q$users$q$ AS n FROM customers c",
    ],
)
def test_rejects_tables_outside_sales_scope(sql):
    with pytest.raises(SQLTableNotAllowedError):
        validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT c.customer_name FROM customers c WHERE c.deleted_at IS NULL",
        "SELECT c.customer_name FROM public.customers c",
        # Words inside string literals are data, not table references.
        "SELECT c.customer_name FROM customers c WHERE c.customer_name ILIKE '%from users%'",
        "SELECT EXTRACT(YEAR FROM i.issued_at) AS nam, SUBSTRING(i.invoice_number FROM 1 FOR 2) AS p "
        "FROM sales_invoices i WHERE i.customer_id IS DISTINCT FROM NULL",
        "SELECT TRIM(BOTH ' ' FROM c.customer_name) AS ten FROM customers c",
        "SELECT d.ngay FROM generate_series(DATE '2025-01-01', DATE '2025-01-31', INTERVAL '1 day') AS d(ngay)",
        "SELECT s.n, c.customer_name FROM (SELECT 1 AS n) s, customers c",
        "SELECT i.invoice_id FROM sales_invoices i LEFT JOIN sales_invoice_lines l ON l.invoice_id = i.invoice_id "
        "CROSS JOIN customers c",
        "WITH ban AS (SELECT i.customer_id FROM sales_invoices i), "
        "tra AS MATERIALIZED (SELECT d.customer_id FROM customer_debt_transactions d) "
        "SELECT ban.customer_id FROM ban FULL JOIN tra ON tra.customer_id = ban.customer_id",
        "WITH RECURSIVE days(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM days WHERE n < 3) "
        "SELECT days.n FROM days",
        "SELECT r.return_id FROM sales_returns r JOIN sales_return_lines rl ON rl.return_id = r.return_id",
    ],
)
def test_accepts_sales_queries(sql):
    assert "LIMIT" in validate(sql)


def test_prompt_examples_pass_validation():
    import json
    import re

    examples = re.findall(r'"sql":"(.*?)"\}\]', SQLPrompt.GENERATION_RULES)
    assert examples
    for sql in examples:
        validate(json.loads(f'"{sql}"'))


def test_every_orm_table_is_classified():
    tables = set(Base.metadata.tables)
    assert ALLOWED_SQL_TABLES.isdisjoint(RESTRICTED_SQL_TABLES)
    unclassified = tables - ALLOWED_SQL_TABLES - RESTRICTED_SQL_TABLES
    assert not unclassified, (
        f"New table(s) {sorted(unclassified)}: add to ALLOWED_SQL_TABLES if Text-to-SQL may "
        "read them, otherwise to RESTRICTED_SQL_TABLES."
    )
