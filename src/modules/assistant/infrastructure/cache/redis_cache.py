import json
import logging

import redis.asyncio as redis
from typing import Optional, Any
from src.modules.assistant.domain.ports.i_cache_service import ICacheService


logger = logging.getLogger(__name__)

_SCAN_COUNT = 500
_DELETE_BATCH_SIZE = 500  # số key mỗi lệnh UNLINK (không chặn server, ít round-trip hơn DEL từng key)


class RedisCache(ICacheService):
    """Redis implementation of cache service"""

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, password: Optional[str] = None):
        self.redis = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            value = await self.redis.get(key)
            return value
        except Exception as e:
            logger.warning("Redis get failed: %s", e)
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL.

        ``str`` được lưu nguyên văn; giá trị khác được ``json.dumps`` (``get`` trả lại chuỗi JSON,
        caller dùng ``json.loads``) để round-trip được thay vì ``str(value)`` kiểu repr Python.
        Giá trị không serialize được → trả False (không ném).
        """
        try:
            payload = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            if ttl:
                await self.redis.setex(key, ttl, payload)
            else:
                await self.redis.set(key, payload)
            return True
        except Exception as e:
            logger.warning("Redis set failed: %s", e)
            return False

    async def delete(self, key: str) -> bool:
        """Delete value from cache"""
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.warning("Redis delete failed: %s", e)
            return False

    async def delete_prefix(self, prefix: str) -> int:
        """Delete all keys with the given prefix (SCAN, never KEYS). Returns 0 on Redis failure."""
        removed = 0
        batch: list[str] = []
        try:
            async for key in self.redis.scan_iter(match=f"{prefix}*", count=_SCAN_COUNT):
                batch.append(key)
                if len(batch) >= _DELETE_BATCH_SIZE:
                    removed += await self.redis.unlink(*batch)
                    batch = []
            if batch:
                removed += await self.redis.unlink(*batch)
            return removed
        except Exception as e:
            logger.warning("Redis delete_prefix failed: %s", e)
            return removed

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        try:
            return await self.redis.exists(key) > 0
        except Exception as e:
            logger.warning("Redis exists failed: %s", e)
            return False