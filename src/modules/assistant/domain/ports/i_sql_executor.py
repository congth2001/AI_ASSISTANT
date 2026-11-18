from abc import ABC, abstractmethod
from typing import Any


class ISQLExecutor(ABC):
    """Read-only SQL execution port for the assistant query pipeline."""

    @abstractmethod
    async def execute_sql(self, sql: str) -> tuple[list[Any], list[str]]:
        """Return rows and column names; implementations enforce read-only execution."""
        raise NotImplementedError
