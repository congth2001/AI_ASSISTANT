"""Dependency wiring owned by the common module."""
from dependency_injector import containers
from dependency_injector.providers import Configuration, Dependency, Singleton

from src.common.infrastructure.database.postgres_client import PostgresClient


class CommonContainer(containers.DeclarativeContainer):
    config = Configuration()

    postgres_client = Singleton(
        PostgresClient,
        url=config.database.url,
        echo=config.database.echo,
    )

    session_factory = postgres_client.provided.session_factory
