import json
from decimal import Decimal

import pytest

from src.application.services.schema_linker import SchemaLinker
from src.application.services.sql_service import (
    SQLQueryPlan,
    SQLService,
    SQLValidationError,
)
from src.application.use_cases.analytics_use_case import AnalyticsUseCase
from src.domain.constants.query_intent import QueryIntent
from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.entities.time_filter import TimeFilter


class RecordingLLM:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    async def generate_response(self, prompt):
        self.prompts.append(prompt)
        return self.response


def analyzed_query(
    *,
    intent=QueryIntent.REVENUE,
    category_name=None,
    customer_name=None,
    invoice_id=None,
    time_filter=None,
):
    return AnalyzedQuery(
        original_query="Câu hỏi kiểm thử",
        normalized="câu hỏi kiểm thử",
        intents=[intent],
        primary_intent=intent,
        category_name=category_name,
        customer_name=customer_name,
        invoice_id=invoice_id,
        time_filter=time_filter or TimeFilter(),
    )


def test_schema_linker_selects_line_grain_and_postgresql_filters():
    linked = SchemaLinker().link(
        analyzed_query(
            intent=QueryIntent.PRODUCT,
            category_name="Gạch",
            time_filter=TimeFilter(year=2025, month=3),
        )
    )

    assert linked.primary_table == "sales_invoice_lines"
    assert linked.filter_hints == {
        "sales_invoices.issued_at.year": 2025,
        "sales_invoices.issued_at.month": 3,
        "sales_invoice_lines.product_category_name": "Gạch",
    }
    assert "sales_invoice_lines.line_amount" in linked.schema_context
    assert "EXTRACT(YEAR FROM i.issued_at)" in linked.schema_context
    assert "strftime" not in linked.schema_context
    assert "invoice_goods" not in linked.schema_context


def test_schema_linker_uses_canonical_steel_category_filter():
    query = analyzed_query(
        intent=QueryIntent.PRODUCT,
        category_name="Sắt",
        time_filter=TimeFilter(year=2025),
    )

    linked = SchemaLinker().link(query)

    assert linked.primary_table == "sales_invoice_lines"
    assert linked.filter_hints["sales_invoice_lines.product_category_name"] == "Sắt"
    assert linked.filter_hints["sales_invoices.issued_at.year"] == 2025


def test_schema_linker_uses_all_canonical_categories_for_category_family():
    query = analyzed_query(intent=QueryIntent.PRODUCT)
    query.category_names = [
        "Bộ thiết bị vệ sinh",
        "Dây thiết bị vệ sinh",
        "Phụ kiện thiết bị vệ sinh",
    ]

    linked = SchemaLinker().link(query)

    assert linked.primary_table == "sales_invoice_lines"
    assert linked.filter_hints[
        "sales_invoice_lines.product_category_name.in"
    ] == query.category_names


def test_schema_linker_maps_customer_and_invoice_to_explicit_columns():
    linked = SchemaLinker().link(
        analyzed_query(
            intent=QueryIntent.CUSTOMER,
            customer_name="Anh Tiệc",
            invoice_id="XB24169-0125",
        )
    )

    assert linked.primary_table == "customers"
    assert linked.filter_hints["customers.customer_name"] == "Anh Tiệc"
    assert linked.filter_hints["sales_invoices.invoice_number"] == "XB24169-0125"


@pytest.mark.asyncio
async def test_generation_prompt_uses_linked_schema_and_json_contract():
    response = json.dumps(
        [
            {
                "intent": "doanh_thu",
                "sql": (
                    "SELECT SUM(i.invoice_total_amount) AS doanh_thu "
                    "FROM sales_invoices i "
                    "WHERE i.deleted_at IS NULL"
                ),
            }
        ]
    )
    llm = RecordingLLM(response)
    service = SQLService(llm)
    linked = SchemaLinker().link(analyzed_query())

    plans = await service.generate(analyzed_query(), linked)

    assert plans[0].intent == "doanh_thu"
    assert "sales_invoices" in plans[0].sql
    prompt = llm.prompts[0]
    assert "LƯỢC ĐỒ CƠ SỞ DỮ LIỆU:" in prompt
    assert "customers.customer_id = sales_invoices.customer_id" in prompt
    assert "gợi ý bộ lọc: {}" in prompt
    assert "Chỉ trả về một JSON array hợp lệ" in prompt
    assert "Luôn dùng bí danh bảng" in prompt
    assert "Công nợ dùng SUM(customer_debt_transactions.amount)" in prompt
    assert 'source_type = \'sales_return\'' in prompt
    assert "bộ lọc thời gian của nhập trả" in prompt
    assert "So sánh doanh thu tháng 2 và tháng 3 năm 2025" in prompt
    assert "CÂU HỎI NGƯỜI DÙNG:\nCâu hỏi kiểm thử" in prompt
    assert not prompt.startswith(" ")


@pytest.mark.asyncio
async def test_generation_prompt_teaches_business_invoice_line_lookup():
    llm = RecordingLLM(
        json.dumps(
            [
                {
                    "intent": "chi_tiet_hoa_don",
                    "sql": (
                        "SELECT l.product_name AS ten_mat_hang "
                        "FROM sales_invoice_lines l"
                    ),
                }
            ]
        )
    )
    service = SQLService(llm)
    query = analyzed_query(
        intent=QueryIntent.PRODUCT,
        invoice_id="XB28606-0925",
    )

    await service.generate(query, SchemaLinker().link(query))

    prompt = llm.prompts[0]
    assert "sales_invoices.invoice_id là khóa kỹ thuật nội bộ" in prompt
    assert "sales_invoices.invoice_number là mã hóa đơn" in prompt
    assert "l.invoice_id = i.invoice_id" in prompt
    assert "i.invoice_number = 'XB28606-0925'" in prompt
    assert '"sales_invoices.invoice_number": "XB28606-0925"' in prompt


def test_parser_fallback_accepts_fenced_cte():
    plans = SQLService._parse("""```sql
        WITH totals AS (
            SELECT SUM(invoice_total_amount) AS amount
            FROM sales_invoices
            WHERE deleted_at IS NULL
        )
        SELECT amount FROM totals;
        ```""")

    assert len(plans) == 1
    assert plans[0].sql.startswith("WITH totals")
    assert plans[0].sql.endswith("SELECT amount FROM totals")


@pytest.mark.asyncio
async def test_repair_prompt_receives_current_schema():
    llm = RecordingLLM(
        '[{"intent":"query","sql":"SELECT i.invoice_number '
        'FROM sales_invoices i WHERE i.deleted_at IS NULL"}]'
    )
    service = SQLService(llm)

    repaired = await service.repair(
        SQLQueryPlan("invoice", "SELECT bad_column FROM sales_invoices"),
        'column "bad_column" does not exist',
        "Table: sales_invoices\n    invoice_number TEXT",
    )

    assert repaired.intent == "invoice"
    assert "invoice_number" in repaired.sql
    assert "Table: sales_invoices" in llm.prompts[0]
    assert "source_type = 'sales_return'" in llm.prompts[0]
    assert "occurred_at" in llm.prompts[0]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM invoice_customers",
        "SELECT * FROM invoice_goods",
        "SELECT * FROM sales_invoices",
        "SELECT DATE '????-??-??'",
    ],
)
def test_validator_rejects_legacy_schema_and_placeholders(sql):
    with pytest.raises(SQLValidationError):
        SQLService(None).validate(sql)


def test_result_summary_prefers_revenue_over_quantity():
    content = AnalyticsUseCase._format_results(
        [
            (
                "products",
                [
                    ("xi măng", Decimal("100"), Decimal("1000")),
                    ("gạch", Decimal("200"), Decimal("900")),
                    ("sắt", Decimal("300"), Decimal("800")),
                ],
                ["product_name", "tong_so_luong", "tong_doanh_thu"],
            )
        ],
        analyzed_query(intent=QueryIntent.PRODUCT),
    )

    assert "→ Cao nhất: {'product_name': 'xi măng'" in content
    assert "→ Thấp nhất: {'product_name': 'sắt'" in content
