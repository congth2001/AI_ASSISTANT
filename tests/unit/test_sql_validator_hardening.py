"""Function allowlist, outer LIMIT handling and quoting checks of the SQL validator."""
import pytest

from src.modules.assistant.application.services.sql_service import SQLService
from src.modules.assistant.domain.errors import SQLValidationError


def validate(sql: str) -> str:
    return SQLService(llm_service=None).validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT query_to_xml('select password_hash from users',true,true,'') AS x",
        "SELECT table_to_xml('users',true,true,'') AS x",
        "SELECT cursor_to_xml('c',1,true,true,'') AS x",
        "SELECT schema_to_xml('public',true,true,'') AS x",
        'SELECT "query_to_xml"(\'select 1\',true,true,\'\') AS x',
        "SELECT public.query_to_xml('select 1',true,true,'') AS x",
        "SELECT QUERY_TO_XML ('select 1',true,true,'') AS x",
        "SELECT set_config('search_path','x',false) AS x",
        "SELECT current_setting('server_version') AS x",
        "SELECT pg_sleep(10) AS x",
        "SELECT lo_import('/etc/passwd') AS x",
        "SELECT dblink('host=x','select 1') AS x",
        "SELECT xpath('/a', 'x'::xml) AS x",
        "SELECT current_user AS x",
        "SELECT c.customer_id FROM customers c WHERE c.customer_id IN (SELECT repeat('x', 1000000000)::uuid)",
        "SELECT CAST(query_to_xml('select 1',true,true,'') AS text) AS x",
        # E-strings and stray quotes can hide text from the scanner.
        "SELECT E'\\'', (SELECT password_hash FROM users), 'x'",
        "SELECT 'abc FROM customers c",
        'SELECT "abc FROM customers c',
    ],
)
def test_rejects_function_and_quoting_bypasses(sql):
    with pytest.raises(SQLValidationError):
        validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(i.invoice_total_amount) AS a, COUNT(*) AS n FROM sales_invoices i",
        "SELECT i.invoice_total_amount::numeric(12,2) AS a, CAST(i.invoice_total_amount AS numeric(10,2)) AS b "
        "FROM sales_invoices i",
        "SELECT d.n FROM generate_series(1, 3) AS d(n)",
        "SELECT s.n FROM (SELECT 1 AS n) s(n)",
        "WITH a(x) AS (SELECT 1), b AS MATERIALIZED (SELECT 2 AS y) SELECT a.x FROM a, b",
        "SELECT ROW_NUMBER() OVER (PARTITION BY i.customer_id ORDER BY i.issued_at) AS r FROM sales_invoices i",
        "SELECT COALESCE(SUM(i.invoice_total_amount) FILTER (WHERE i.issued_at > DATE '2025-01-01'), 0) AS a "
        "FROM sales_invoices i",
        "SELECT i.invoice_id FROM sales_invoices i WHERE i.customer_id IN (SELECT c.customer_id FROM customers c) "
        "AND EXISTS (SELECT 1 FROM customers c2)",
        "SELECT date_trunc('month', i.issued_at) AS m, ROUND(AVG(i.invoice_total_amount), 2) AS a "
        "FROM sales_invoices i GROUP BY 1",
        "SELECT i.invoice_id FROM sales_invoices i WHERE (i.invoice_id, i.customer_id) IN (VALUES (1, 2))",
        "SELECT c.customer_name FROM customers c WHERE c.customer_name ILIKE '%it''s%'",
    ],
)
def test_accepts_allowlisted_functions(sql):
    assert "LIMIT" in validate(sql)


def test_limit_in_subquery_does_not_satisfy_outer_limit():
    sql = validate("SELECT x.n FROM (SELECT i.invoice_id AS n FROM sales_invoices i LIMIT 5) x")
    assert sql.endswith("\nLIMIT 1000")


@pytest.mark.parametrize(
    "raw",
    [
        "SELECT i.invoice_id FROM sales_invoices i LIMIT ALL",
        "SELECT i.invoice_id FROM sales_invoices i LIMIT NULL",
        "SELECT i.invoice_id FROM sales_invoices i FETCH FIRST 5000 ROWS ONLY",
        "SELECT i.invoice_id FROM sales_invoices i LIMIT 5 + 1",
    ],
)
def test_unusual_outer_limits_are_wrapped(raw):
    sql = validate(raw)
    assert sql.startswith("SELECT * FROM (\n")
    assert sql.endswith(") AS q\nLIMIT 1000")


def test_offset_without_limit_gets_a_valid_limit():
    assert validate("SELECT i.invoice_id FROM sales_invoices i ORDER BY 1 OFFSET 5").endswith(
        "OFFSET 5\nLIMIT 1000"
    )


def test_offset_then_limit_is_kept_and_capped():
    assert validate(
        "SELECT i.invoice_id FROM sales_invoices i ORDER BY 1 OFFSET 5 LIMIT 99999"
    ).endswith("OFFSET 5 LIMIT 1000")
    assert validate(
        "SELECT i.invoice_id FROM sales_invoices i ORDER BY 1 LIMIT 10 OFFSET 5"
    ).endswith("LIMIT 10 OFFSET 5")


def test_order_by_is_untouched_when_limit_is_appended():
    sql = validate("SELECT i.invoice_id FROM sales_invoices i ORDER BY i.issued_at DESC")
    assert sql == "SELECT i.invoice_id FROM sales_invoices i ORDER BY i.issued_at DESC\nLIMIT 1000"


@pytest.mark.parametrize(
    "sql",
    [
        # An operator before "(" is not a call: these were rejected as `i.issued_at()`.
        "WITH params AS (SELECT DATE '2026-07-21' AS tu_ngay) SELECT COUNT(i.invoice_id) AS so_hoa_don "
        "FROM sales_invoices i WHERE i.deleted_at IS NULL AND i.issued_at >= (SELECT p.tu_ngay FROM params p)",
        "SELECT COUNT(d.customer_id) AS so_but_toan FROM customer_debt_transactions d "
        "WHERE d.deleted_at IS NULL AND d.occurred_at < (SELECT MAX(x.occurred_at) FROM customer_debt_transactions x)",
        "SELECT i.invoice_total_amount * (1 - 0.1) AS gia_tri FROM sales_invoices i WHERE i.deleted_at IS NULL",
        "SELECT i.invoice_total_amount::numeric(18, 2) AS gia_tri FROM sales_invoices i WHERE i.deleted_at IS NULL",
        # CTE written without a space before "(".
        "WITH ban_ky_truoc AS(SELECT COUNT(i.invoice_id) AS so_hoa_don FROM sales_invoices i "
        "WHERE i.deleted_at IS NULL) SELECT b.so_hoa_don FROM ban_ky_truoc b",
    ],
)
def test_accepts_operators_before_parentheses_and_compact_ctes(sql):
    validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 AS x WHERE 1 = pg_sleep(1) IS NULL",
        "SELECT i.invoice_id FROM sales_invoices i WHERE i.issued_at >= (SELECT pg_sleep(1))",
        "WITH alias AS(SELECT u.email FROM users u) SELECT a.email FROM alias a",
        "SELECT i.invoice_id FROM sales_invoices i, alias(1) a",
    ],
)
def test_operator_tokens_do_not_hide_calls_or_tables(sql):
    with pytest.raises(SQLValidationError):
        validate(sql)
