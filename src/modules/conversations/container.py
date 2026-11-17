"""Dependency wiring owned by the conversations module."""
from dependency_injector import containers
from dependency_injector.providers import Dependency, Singleton

from src.modules.conversations.application.use_cases.conversation_use_case import ConversationUseCase
from src.modules.conversations.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)


class ConversationsContainer(containers.DeclarativeContainer):
    session_factory = Dependency()

    conversation_repo = Singleton(
        ConversationRepository, session_factory=session_factory
    )

    use_case_conversation = Singleton(
        ConversationUseCase,
        conversation_repo=conversation_repo,
    )
