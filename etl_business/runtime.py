"""Process-level helpers shared by the ETL entry points (lock + cache)."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from filelock import FileLock, Timeout

from src.common.cache_keys import CHAT_RESPONSE_CACHE_PREFIX

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALREADY_RUNNING_MESSAGE = "Another business ETL job is already running"


def resolve_backend_path(value: str | Path) -> Path:
    """Resolve a configured path the same way the ETL runtime does (relative to backend/)."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def resolve_lock_path(lock_path: str | Path) -> Path:
    """Resolve the configured lock path the same way the ETL runtime does."""
    return resolve_backend_path(lock_path)


@contextmanager
def exclusive_etl_lock(lock_path: str | Path) -> Iterator[None]:
    """Fail immediately when another ETL/sync process holds the lock.

    ``run_business_etl.py`` and ``sync_business_data.py`` share this lock so a
    manual sync cannot interleave with the scheduled job.
    """
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path), timeout=0)
    try:
        lock.acquire()
    except Timeout as exc:
        raise RuntimeError(ALREADY_RUNNING_MESSAGE) from exc
    try:
        yield
    finally:
        lock.release()


async def invalidate_chat_response_cache(get_cache_service: Callable[[], Any]) -> bool:
    """Drop cached chat answers; a cache outage must not fail a finished sync.

    Takes a factory so that failures while building the cache client are also
    contained.
    """
    try:
        await get_cache_service().delete_prefix(CHAT_RESPONSE_CACHE_PREFIX)
    except Exception:
        logger.warning(
            "Could not invalidate chat response cache; entries expire by TTL",
            exc_info=True,
        )
        return False
    return True
