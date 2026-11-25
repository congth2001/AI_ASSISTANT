"""Dependency wiring owned by the auth module."""
from dependency_injector import containers
from dependency_injector.providers import Configuration, Dependency, Singleton

from src.modules.auth.application.use_cases.auth_use_case import AuthUseCase
from src.modules.auth.infrastructure.repositories.auth_repository import AuthRepository

from src.modules.auth.infrastructure.security import BcryptPasswordHasher, JWTTokenService


class AuthContainer(containers.DeclarativeContainer):
    config = Configuration()
    session_factory = Dependency()

    auth_repository = Singleton(AuthRepository, session_factory=session_factory)

    password_hasher = Singleton(BcryptPasswordHasher)
    token_service = Singleton(
        JWTTokenService,
        secret=config.auth.jwt_secret,
        issuer=config.auth.jwt_issuer,
        audience=config.auth.jwt_audience,
    )

    auth_use_case = Singleton(
        AuthUseCase,
        auth_repository=auth_repository,
        password_hasher=password_hasher,
        token_service=token_service,
        access_token_minutes=config.auth.access_token_minutes,
        refresh_token_days=config.auth.refresh_token_days,
        refresh_reuse_grace_seconds=config.auth.refresh_reuse_grace_seconds,
        guest_token_minutes=config.auth.guest_token_minutes,
    )
