from abc import ABC, abstractmethod


class IPasswordHasher(ABC):
    @abstractmethod
    def hash(self, password: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def verify(self, password: str, password_hash: str) -> bool:
        raise NotImplementedError
