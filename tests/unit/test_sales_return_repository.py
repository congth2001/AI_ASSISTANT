from src.infrastructure.repositories.sales_return_repository import SalesReturnRepository


def test_return_line_numbers_survive_reordering_and_reappearance():
    # Include a soft-deleted line: its unique keys still occupy a line number.
    existing = [
        ("return-1", "line-a", 1),
        ("return-1", "line-b", 2),
        ("return-1", "line-old", 3),
        ("return-2", "line-x", 1),
    ]
    incoming = [
        {"return_id": "return-1", "source_line_id": "line-b", "line_number": 1},
        {"return_id": "return-1", "source_line_id": "line-a", "line_number": 2},
        {"return_id": "return-1", "source_line_id": "line-new", "line_number": 3},
        {"return_id": "return-2", "source_line_id": "line-x", "line_number": 1},
        {"return_id": "return-2", "source_line_id": "line-y", "line_number": 2},
    ]

    SalesReturnRepository._assign_line_numbers(incoming, existing)

    assert [line["line_number"] for line in incoming] == [2, 1, 4, 1, 2]
    assert len({(line["return_id"], line["line_number"]) for line in incoming}) == len(incoming)

    reappearing = [{"return_id": "return-1", "source_line_id": "line-old"}]
    SalesReturnRepository._assign_line_numbers(reappearing, existing)
    assert reappearing[0]["line_number"] == 3
