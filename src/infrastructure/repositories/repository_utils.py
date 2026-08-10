from decimal import Decimal
from typing import Any, Iterator, Sequence, TypeVar

T = TypeVar("T")


def model_to_dict(model: Any) -> dict[str, Any]:
    return {
        column.key: getattr(model, column.key) for column in model.__table__.columns
    }


def to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def chunked(values: Sequence[T], size: int = 1000) -> Iterator[Sequence[T]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]
