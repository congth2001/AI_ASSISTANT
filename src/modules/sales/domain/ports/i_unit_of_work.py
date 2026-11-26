from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import AsyncIterator


class IUnitOfWork(ABC):
    """Runs several repository calls as one atomic transaction."""

    @abstractmethod
    def transaction(self) -> AbstractAsyncContextManager[None]:
        """Commit on clean exit, roll back every repository write on error.

        Entering while a transaction is already active joins it; only the
        outermost context commits.
        """


class NullUnitOfWork(IUnitOfWork):
    """No-op unit of work for repositories that manage their own commits."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield
