import logging

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)


class PostgresClient:
    def __init__(
        self,
        url: str | URL,
        echo: bool = False,
    ):
        # pool_pre_ping discards connections dropped while idle (Docker/network restarts).
        self._engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info("Configured PostgreSQL engine for %s", self._engine.url.host)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def close(self) -> None:
        await self._engine.dispose()
        logger.info("PostgreSQL connection closed")
