"""Shared-session unit of work for the sales repositories."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.sales.domain.ports.i_unit_of_work import IUnitOfWork

_active_session: ContextVar[AsyncSession | None] = ContextVar(
    "sales_active_session", default=None
)


class SqlAlchemyUnitOfWork(IUnitOfWork):
    """Binds one AsyncSession to the current task for the whole transaction.

    Repositories obtain their session through ``repository_session``: inside
    ``transaction()`` they all share the same session and never commit on
    their own; outside it each call keeps its previous commit-per-call
    behaviour.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        if _active_session.get() is not None:
            yield
            return
        async with self._session_factory() as session:
            token = _active_session.set(session)
            try:
                yield
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
            finally:
                _active_session.reset(token)


@asynccontextmanager
async def repository_session(session_factory) -> AsyncIterator[AsyncSession]:
    """Yield the active transaction session, or a self-committing one."""
    active = _active_session.get()
    if active is not None:
        yield active
        return
    async with session_factory() as session:
        yield session
        await session.commit()
