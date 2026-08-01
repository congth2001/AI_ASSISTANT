import pytest

from src.application.services.query_analyzer import QueryAnalyzer


def analyzer(*customer_names: str) -> QueryAnalyzer:
    return QueryAnalyzer(customer_names=list(customer_names))


@pytest.mark.parametrize(
    ("query", "customer_names"),
    [
        ("Doanh thu tháng 3 năm 2025 là bao nhiêu?", ["Doanh"]),
        ("Tổng doanh thu tháng này", ["Doanh Thu"]),
        ("Top 5 khách hàng mua nhiều nhất", ["Mua", "Nhiều"]),
        ("Công nợ khách hàng tháng này", ["Công", "Nợ"]),
        ("Khách hàng nào có doanh thu cao nhất?", ["Nào", "Doanh"]),
    ],
)
def test_business_terms_are_not_extracted_as_customer_names(query, customer_names):
    result = analyzer(*customer_names).analyze(query)

    assert result.customer_name is None
    assert result.customer_score == 0


@pytest.mark.parametrize(
    ("query", "customer_names", "expected"),
    [
        ("Doanh thu của anh Doanh tháng này", ["Doanh"], "Doanh"),
        ("Chị Thu còn nợ bao nhiêu?", ["Thu"], "Thu"),
        ("Doanh thu khách hàng Tiệc X3", ["Tiệc X3"], "Tiệc X3"),
        ("Doanh thu khách hàng tên Doanh", ["Doanh"], "Doanh"),
        ("Doanh thu của Tiệc X3", ["Tiệc X3"], "Tiệc X3"),
        ("Anh Tiec X3 còn nợ bao nhiêu?", ["Tiệc X3"], "Tiệc X3"),
        ("ANH MINH đã mua gì?", ["Anh Minh"], "Anh Minh"),
    ],
)
def test_exact_customer_matching_requires_safe_context(
    query,
    customer_names,
    expected,
):
    result = analyzer(*customer_names).analyze(query)

    assert result.customer_name == expected
    assert result.customer_score == 100
    assert "customer_id" in result.milvus_filter


def test_multi_token_typo_is_fuzzy_matched_after_person_title():
    result = analyzer("Khiêm X3", "Tiệc X3").analyze(
        "Anh Khieem X3 còn nợ bao nhiêu?"
    )

    assert result.customer_name == "Khiêm X3"
    assert 84 <= result.customer_score < 100


@pytest.mark.parametrize(
    ("query", "customer_names"),
    [
        ("Anh Min còn nợ bao nhiêu?", ["Minh"]),
        ("Anh Tiec X còn nợ bao nhiêu?", ["Tiệc X3", "Tiệc X4"]),
        ("Anh Nguyen Van An mua gì?", ["Nguyễn Văn An", "Nguyễn Văn Ân"]),
        ("Anh Minh còn nợ bao nhiêu?", ["Anh Minh", "Anh Minh"]),
        ("So sánh Tiệc X3 và Khiêm X3", ["Tiệc X3", "Khiêm X3"]),
    ],
)
def test_ambiguous_or_unsafe_customer_match_is_rejected(query, customer_names):
    result = analyzer(*customer_names).analyze(query)

    assert result.customer_name is None
    assert result.customer_score == 0


def test_no_customer_dictionary_returns_no_match():
    result = analyzer().analyze("Anh Minh còn nợ bao nhiêu?")

    assert result.customer_name is None
    assert result.customer_score == 0


def test_steel_phrase_maps_to_canonical_steel_category():
    query_analyzer = QueryAnalyzer(
        customer_names=[],
        category_names=["Sắt", "Gạch", "Phụ kiện xây dựng"],
    )

    result = query_analyzer.analyze(
        "Doanh thu các mặt hàng sắt thép cụ thể như nào trong năm 2025?"
    )

    assert result.category_name == "Sắt"
    assert result.category_score == 100
    assert result.time_filter.year == 2025


def test_multiple_independent_categories_are_not_collapsed_to_one():
    query_analyzer = QueryAnalyzer(category_names=["Sắt", "Gạch"])

    result = query_analyzer.analyze("So sánh doanh thu Gạch và Sắt năm 2025")

    assert result.category_name is None


def test_longest_nested_category_is_selected():
    query_analyzer = QueryAnalyzer(
        category_names=["Phụ kiện", "Phụ kiện xây dựng"]
    )

    result = query_analyzer.analyze("Doanh thu phụ kiện xây dựng năm 2025")

    assert result.category_name == "Phụ kiện xây dựng"


def test_category_family_does_not_fold_ve_into_short_ve_category():
    query_analyzer = QueryAnalyzer(
        category_names=[
            "Bộ thiết bị vệ sinh",
            "Dây thiết bị vệ sinh",
            "Phụ kiện thiết bị vệ sinh",
            "Phụ kiện vệ sinh",
            "Ve",
        ]
    )

    result = query_analyzer.analyze(
        "Thiết bị vệ sinh gồm những mặt hàng cụ thể nào?"
    )

    assert result.category_name is None
    assert result.category_names == [
        "Bộ thiết bị vệ sinh",
        "Dây thiết bị vệ sinh",
        "Phụ kiện thiết bị vệ sinh",
    ]
    assert result.category_score == 95
    assert result.top_n is None


def test_short_category_requires_accent_sensitive_exact_match():
    query_analyzer = QueryAnalyzer(category_names=["Ve"])

    false_positive = query_analyzer.analyze("Thiết bị vệ sinh gồm những gì?")
    exact = query_analyzer.analyze("Danh mục Ve gồm những gì?")

    assert false_positive.category_name is None
    assert false_positive.category_names == []
    assert exact.category_name == "Ve"
    assert exact.category_names == ["Ve"]


def test_explicit_top_n_is_extracted_but_exhaustive_list_has_no_limit():
    query_analyzer = QueryAnalyzer(category_names=["Sắt"])

    ranked = query_analyzer.analyze("Top 5 mặt hàng sắt bán chạy nhất")
    exhaustive = query_analyzer.analyze("Mặt hàng sắt gồm những loại nào?")

    assert ranked.top_n == 5
    assert exhaustive.top_n is None
