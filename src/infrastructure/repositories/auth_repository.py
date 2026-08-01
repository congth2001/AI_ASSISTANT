from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.domain.repositories.i_auth_repository import IAuthRepository
from src.infrastructure.repositories.models import RefreshTokenModel, UserModel


class DuplicateEmailError(ValueError):
    pass


class AuthRepository(IAuthRepository):
    def __init__(self, session_factory):
        self.session_factory = session_factory

    @staticmethod
    def _to_dict(model: UserModel) -> Dict[str, Any]:
        return {key: value for key, value in model.__dict__.items() if not key.startswith("_")}

    async def create_user(
        self, email: Optional[str], display_name: str, password_hash: Optional[str], role: str
    ) -> Dict[str, Any]:
        async with self.session_factory() as session:
            user = UserModel(
                id=str(uuid4()),
                email=email,
                display_name=display_name,
                password_hash=password_hash,
                role=role,
            )
            session.add(user)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateEmailError("Email is already registered") from exc
            await session.refresh(user)
            return self._to_dict(user)

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(select(UserModel).where(UserModel.email == email))
            user = result.scalar_one_or_none()
            return self._to_dict(user) if user else None

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(select(UserModel).where(UserModel.id == user_id))
            user = result.scalar_one_or_none()
            return self._to_dict(user) if user else None

    async def store_refresh_token(self, jti: str, user_id: str, expires_at: datetime) -> None:
        async with self.session_factory() as session:
            session.add(RefreshTokenModel(jti=jti, user_id=user_id, expires_at=expires_at))
            await session.commit()

    async def consume_refresh_token(self, jti: str, user_id: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(RefreshTokenModel)
                .where(
                    RefreshTokenModel.jti == jti,
                    RefreshTokenModel.user_id == user_id,
                    RefreshTokenModel.revoked_at.is_(None),
                    RefreshTokenModel.expires_at > datetime.now(timezone.utc),
                )
                .values(revoked_at=datetime.now(timezone.utc))
            )
            await session.commit()
            return result.rowcount == 1

    async def revoke_refresh_token(self, jti: str, user_id: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(RefreshTokenModel)
                .where(
                    RefreshTokenModel.jti == jti,
                    RefreshTokenModel.user_id == user_id,
                    RefreshTokenModel.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(timezone.utc))
            )
            await session.commit()
