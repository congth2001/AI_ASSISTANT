from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy import and_, column, delete, exists, func, or_, select, table, update
from sqlalchemy.exc import IntegrityError

from src.common.infrastructure.database.orm_utils import model_to_dict
from src.modules.auth.domain.repositories.i_auth_repository import IAuthRepository, RefreshRotation
from src.modules.auth.infrastructure.models import RefreshTokenModel, UserModel
from src.modules.auth.domain.errors import (
    DuplicateEmailError,
)


class AuthRepository(IAuthRepository):
    def __init__(self, session_factory):
        self.session_factory = session_factory

    @staticmethod
    def _to_dict(model: UserModel) -> Dict[str, Any]:
        return model_to_dict(model)

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
                raise DuplicateEmailError() from exc
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

    async def rotate_refresh_token(
        self,
        jti: str,
        user_id: str,
        new_jti: str,
        new_expires_at: datetime,
        reuse_grace_seconds: int = 0,
    ) -> RefreshRotation:
        now = datetime.now(timezone.utc)
        # One transaction: consume + store (or revoke-all on replay) commit or roll back together.
        async with self.session_factory() as session, session.begin():
            consumed = await session.execute(
                update(RefreshTokenModel)
                .where(
                    RefreshTokenModel.jti == jti,
                    RefreshTokenModel.user_id == user_id,
                    RefreshTokenModel.revoked_at.is_(None),
                    RefreshTokenModel.expires_at > now,
                )
                .values(revoked_at=now)
            )
            if consumed.rowcount == 1:
                session.add(RefreshTokenModel(jti=new_jti, user_id=user_id, expires_at=new_expires_at))
                return RefreshRotation.ROTATED

            revoked_at = (
                await session.execute(
                    select(RefreshTokenModel.revoked_at).where(
                        RefreshTokenModel.jti == jti, RefreshTokenModel.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
            if revoked_at is None:
                return RefreshRotation.INVALID  # unknown, or expired without ever being used
            if revoked_at.tzinfo is None:  # legacy/naive values are UTC
                revoked_at = revoked_at.replace(tzinfo=timezone.utc)
            if now - revoked_at < timedelta(seconds=reuse_grace_seconds):
                return RefreshRotation.INVALID  # concurrent refresh from the same client
            await self._revoke_active_tokens(session, user_id, now)
            return RefreshRotation.REUSED

    async def revoke_refresh_token(self, jti: str, user_id: str) -> None:
        """Logout: delete the token instead of marking it revoked.

        Revoked rows are kept only for rotated tokens so a replay can be detected;
        a logged-out token that is sent again is simply unknown (INVALID) and must
        not revoke the user's other sessions.
        """
        async with self.session_factory() as session:
            await session.execute(
                delete(RefreshTokenModel).where(
                    RefreshTokenModel.jti == jti,
                    RefreshTokenModel.user_id == user_id,
                    RefreshTokenModel.revoked_at.is_(None),
                )
            )
            await session.commit()

    async def revoke_all_refresh_tokens(self, user_id: str) -> int:
        async with self.session_factory() as session, session.begin():
            return await self._revoke_active_tokens(session, user_id, datetime.now(timezone.utc))

    @staticmethod
    async def _revoke_active_tokens(session, user_id: str, now: datetime) -> int:
        result = await session.execute(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.user_id == user_id, RefreshTokenModel.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        return result.rowcount

    async def purge_expired_auth_data(
        self,
        guest_created_before: datetime,
        refresh_expired_before: datetime,
        revoked_before: datetime,
        dry_run: bool = True,
    ) -> Dict[str, int]:
        # Lightweight table reference: auth must not import the conversations module's models.
        conversations = table("conversations", column("user_id"))
        guest_filter = and_(
            UserModel.role == "guest",
            UserModel.created_at < guest_created_before,
            ~exists().where(conversations.c.user_id == UserModel.id),
        )
        token_filter = or_(
            RefreshTokenModel.expires_at < refresh_expired_before,
            and_(RefreshTokenModel.revoked_at.is_not(None), RefreshTokenModel.revoked_at < revoked_before),
        )
        async with self.session_factory() as session, session.begin():
            if dry_run:
                guests = await session.scalar(select(func.count()).select_from(UserModel).where(guest_filter))
                tokens = await session.scalar(
                    select(func.count()).select_from(RefreshTokenModel).where(token_filter)
                )
                return {"guest_users": guests or 0, "refresh_tokens": tokens or 0}
            tokens = (await session.execute(delete(RefreshTokenModel).where(token_filter))).rowcount
            # Remaining tokens of deleted guests are removed by ON DELETE CASCADE.
            guests = (await session.execute(delete(UserModel).where(guest_filter))).rowcount
            return {"guest_users": guests, "refresh_tokens": tokens}
