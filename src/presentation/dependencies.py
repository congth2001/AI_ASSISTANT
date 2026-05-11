from src.presentation.session_resource_factory import SessionResourceFactory
from src.domain.entities.user import User


def mininmum_resource_factory_builder():
    return SessionResourceFactory()


def verify_user(user_id: str) -> User:
    return User(id=user_id)
