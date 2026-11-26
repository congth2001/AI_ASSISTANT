from decimal import Decimal

from evals.execution_eval import (
    QueryResult,
    canonical_result,
    results_equal,
    summary_metrics,
)


def test_numeric_values_compare_by_value_not_numeric_representation():
    actual = QueryResult(("revenue",), ((Decimal("7000.00"),),))
    expected = QueryResult(("doanh_thu",), ((7000,),))

    assert results_equal(actual, expected, ordered=False)
    assert not results_equal(actual, expected, ordered=False, compare_columns=True)


def test_unordered_results_ignore_row_order_but_ordered_results_do_not():
    first = QueryResult(("name", "amount"), (("A", 10), ("B", 20)))
    second = QueryResult(("name", "amount"), (("B", 20), ("A", 10)))

    assert results_equal(first, second, ordered=False)
    assert not results_equal(first, second, ordered=True)


def test_canonical_result_preserves_null_text_and_decimal_types():
    result = QueryResult(("value",), ((None,), ("1",), (Decimal("1.000"),)))

    normalized = canonical_result(result, ordered=True)

    assert normalized["rows"] == [[None], ["1"], [{"$number": "1"}]]


def test_execution_accuracy_uses_all_cases_as_denominator():
    details = [
        {"case_id": "a", "status": "correct"},
        {"case_id": "b", "status": "wrong_result"},
        {"case_id": "c", "status": "execution_error"},
        {"case_id": "d", "status": "missing_prediction"},
    ]

    assert summary_metrics(details, 4) == {
        "total_cases": 4,
        "predictions_covered": 3,
        "queries_executed_successfully": 2,
        "correct_results": 1,
        "coverage": 0.75,
        "execution_success_rate": 0.5,
        "execution_result_accuracy": 0.25,
    }



# ── Column-subset matching and accepted alternatives ───────────────────────

from evals.execution_eval import accepted_query_results, results_match, validate_case_set  # noqa: E402


def test_extra_and_reordered_columns_match_only_when_allowed():
    expected = QueryResult(("ten", "doanh_thu"), (("An Phát", 6100), ("Bình Minh", 5200)))
    actual = QueryResult(
        ("ma", "doanh_thu_thuan", "ten_khach_hang"),
        (("id-1", Decimal("6100.00"), "An Phát"), ("id-2", Decimal("5200.00"), "Bình Minh")),
    )

    assert results_match(actual, expected, ordered=True, allow_extra_columns=True)
    assert not results_match(actual, expected, ordered=True, allow_extra_columns=False)


def test_subset_match_still_rejects_wrong_values_extra_rows_and_split_groups():
    expected = QueryResult(("ten", "doanh_thu"), (("Thép D10", 4200),))
    wrong_value = QueryResult(("ten", "dt", "dvt"), (("Thép D10", 2500, "cây"),))
    split_rows = QueryResult(("ten", "dt", "don_gia"), (("Thép D10", 2500, 62.5), ("Thép D10", 1700, 60)))

    assert not results_match(wrong_value, expected, ordered=True, allow_extra_columns=True)
    assert not results_match(split_rows, expected, ordered=True, allow_extra_columns=True)


def test_subset_match_keeps_row_pairing_across_columns():
    expected = QueryResult(("ten", "doanh_thu"), (("A", 1), ("B", 2)))
    # Each column alone has the right values, but rows pair A with 2.
    crossed = QueryResult(("ten", "doanh_thu", "x"), (("A", 2, 0), ("B", 1, 0)))

    assert not results_match(crossed, expected, ordered=False, allow_extra_columns=True)


def test_accepted_results_accept_typed_values_and_are_validated():
    case = {
        "id": "rev", "question": "q", "reference_sql": "SELECT 1", "ordered": True,
        "expected_result": {"columns": ["thang"], "rows": [[1]]},
        "accepted_results": [{"columns": ["thang"], "rows": [[{"$datetime": "2025-01-01T00:00:00"}]]}],
    }
    validate_case_set([case])
    from datetime import datetime

    actual = QueryResult(("thang_nam",), ((datetime(2025, 1, 1),),))
    (alternative,) = accepted_query_results(case)
    assert results_equal(actual, alternative, ordered=True)

    broken = {**case, "accepted_results": [{"columns": ["thang"]}]}
    try:
        validate_case_set([broken])
    except ValueError:
        pass
    else:
        raise AssertionError("accepted_results without rows must be rejected")
