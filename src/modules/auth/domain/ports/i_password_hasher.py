from abc import ABC, abstractmethod

# bcrypt only uses the first 72 BYTES of the UTF-8 encoded password.
MAX_PASSWORD_BYTES = 72


def password_byte_length(password: str) -> int:
    return len(password.encode("utf-8"))


class IPasswordHasher(ABC):
    """Password hashing is CPU bound; implementations must not block the event loop."""

    @property
    @abstractmethod
    def dummy_hash(self) -> str:
        """Fixed hash (same cost as real ones) used to equalise timing when no user matches."""
        raise NotImplementedError

    @abstractmethod
    async def hash(self, password: str) -> str:
        """Hash a password; raises PasswordTooLongError above MAX_PASSWORD_BYTES."""
        raise NotImplementedError

    @abstractmethod
    async def verify(self, password: str, password_hash: str) -> bool:
        """Return False for a wrong password and for malformed hashes; never raise on them."""
        raise NotImplementedError
