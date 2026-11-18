from abc import ABC, abstractmethod
from typing import Any


class ITokenService(ABC):
    @abstractmethod
    def encode(self, claims: dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def decode(self, token: str, expected_type: str) -> dict[str, Any]:
        """Validate signature, expiry, issuer, audience and token type."""
        raise NotImplementedError
