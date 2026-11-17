import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.assistant.infrastructure.cache.redis_cache import RedisCache


def _cache(fake) -> RedisCache:
    cache = RedisCache()
    cache.redis = fake
    return cache


@pytest.mark.asyncio
async def test_set_keeps_strings_verbatim_and_json_encodes_other_values():
    fake = MagicMock()
    fake.set = AsyncMock()
    fake.setex = AsyncMock()
    cache = _cache(fake)

    assert await cache.set("k1", "plain text") is True
    fake.set.assert_awaited_with("k1", "plain text")

    assert await cache.set("k2", {"a": [1, 2], "vi": "tiếng Việt"}, ttl=30) is True
    key, ttl, payload = fake.setex.await_args.args
    assert (key, ttl) == ("k2", 30)
    assert json.loads(payload) == {"a": [1, 2], "vi": "tiếng Việt"}  # round-trip, không phải repr Python

    assert await cache.set("k3", 5) is True
    fake.set.assert_awaited_with("k3", "5")
    assert await cache.set("k4", True) is True
    fake.set.assert_awaited_with("k4", "true")


@pytest.mark.asyncio
async def test_set_returns_false_for_unserializable_value():
    fake = MagicMock()
    fake.set = AsyncMock()
    assert await _cache(fake).set("k", object()) is False
    fake.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_prefix_unlinks_in_batches():
    keys = [f"p:{i}" for i in range(1203)]

    async def scan_iter(match, count):
        assert match == "p:*"
        for k in keys:
            yield k

    fake = MagicMock()
    fake.scan_iter = scan_iter
    fake.unlink = AsyncMock(side_effect=lambda *ks: len(ks))
    removed = await _cache(fake).delete_prefix("p:")

    assert removed == 1203
    assert [len(c.args) for c in fake.unlink.await_args_list] == [500, 500, 203]


@pytest.mark.asyncio
async def test_delete_prefix_returns_partial_count_on_failure():
    async def scan_iter(match, count):
        for i in range(600):
            yield f"p:{i}"

    fake = MagicMock()
    fake.scan_iter = scan_iter
    fake.unlink = AsyncMock(side_effect=[500, RuntimeError("redis down")])
    assert await _cache(fake).delete_prefix("p:") == 500


@pytest.mark.asyncio
async def test_delete_prefix_without_matches_issues_no_command():
    async def scan_iter(match, count):
        return
        yield  # pragma: no cover

    fake = MagicMock()
    fake.scan_iter = scan_iter
    fake.unlink = AsyncMock()
    assert await _cache(fake).delete_prefix("none:") == 0
    fake.unlink.assert_not_awaited()
