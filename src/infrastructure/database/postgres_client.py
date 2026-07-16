import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


class PostgresClient():
    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        username: str = "postgres",
        password: str = "postgres",
        db_name: str = "ai_assistant",
        echo: bool = False,
    ):
        url = f"postgresql+asyncpg://{username}:{password}@{host}:{port}/{db_name}"
        self._engine: AsyncEngine = create_async_engine(url, echo=echo)
        self._session_factory = sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info(f"Connected to PostgreSQL at {host}:{port}/{db_name}")

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self):
        return self._session_factory

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def init_db(self, base) -> None:
        """Create all tables defined in SQLAlchemy models."""
        async with self._engine.begin() as conn:
            await conn.run_sync(base.metadata.create_all)
        logger.info("Database tables created")

    async def close(self) -> None:
        await self._engine.dispose()
        logger.info("PostgreSQL connection closed")
