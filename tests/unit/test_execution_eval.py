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

