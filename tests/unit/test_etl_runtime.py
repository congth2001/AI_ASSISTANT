"""ETL entry-point plumbing: shared lock, best-effort cache invalidation, CLI flags."""
import logging

import pytest
from filelock import FileLock

from etl_business import runtime
from etl_business.job import run_business_etl
from src.common.cache_keys import CHAT_RESPONSE_CACHE_PREFIX


def test_exclusive_lock_rejects_second_holder(tmp_path):
    lock_path = tmp_path / "locks" / "etl.lock"

    with runtime.exclusive_etl_lock(lock_path):
        with pytest.raises(RuntimeError, match="already running"):
            with runtime.exclusive_etl_lock(lock_path):
                pass

    with runtime.exclusive_etl_lock(lock_path):  # released afterwards
        pass


def test_exclusive_lock_is_released_when_body_fails(tmp_path):
    lock_path = tmp_path / "etl.lock"

    with pytest.raises(ValueError):
        with runtime.exclusive_etl_lock(lock_path):
            raise ValueError("boom")

    with runtime.exclusive_etl_lock(lock_path):
        pass


def test_body_errors_are_not_mistaken_for_lock_contention(tmp_path):
    from filelock import Timeout

    with pytest.raises(Timeout):
        with runtime.exclusive_etl_lock(tmp_path / "etl.lock"):
            raise Timeout(str(tmp_path / "other.lock"))


def test_relative_lock_path_resolves_against_backend_root():
    resolved = runtime.resolve_lock_path("data/etl/business-etl.lock")

    assert resolved.is_absolute()
    assert resolved == (runtime.PROJECT_ROOT / "data/etl/business-etl.lock").resolve()


@pytest.mark.asyncio
async def test_run_business_etl_refuses_to_start_while_lock_is_held(tmp_path):
    lock_path = tmp_path / "etl.lock"
    config = {"_runtime": {"lock_path": str(lock_path)}}

    with FileLock(str(lock_path), timeout=0):
        with pytest.raises(RuntimeError, match="already running"):
            await run_business_etl(config)


class RecordingCache:
    def __init__(self):
        self.prefixes = []

    async def delete_prefix(self, prefix):
        self.prefixes.append(prefix)
        return 1


@pytest.mark.asyncio
async def test_cache_invalidation_deletes_chat_response_prefix():
    cache = RecordingCache()

    assert await runtime.invalidate_chat_response_cache(lambda: cache) is True
    assert cache.prefixes == [CHAT_RESPONSE_CACHE_PREFIX]


@pytest.mark.asyncio
async def test_cache_outage_is_logged_but_does_not_fail_the_sync(caplog):
    class BrokenCache:
        async def delete_prefix(self, prefix):
            raise ConnectionError("redis down")

    def broken_factory():
        raise ConnectionError("cannot build client")

    with caplog.at_level(logging.WARNING, logger=runtime.logger.name):
        assert await runtime.invalidate_chat_response_cache(lambda: BrokenCache()) is False
        assert await runtime.invalidate_chat_response_cache(broken_factory) is False

    assert "Could not invalidate chat response cache" in caplog.text


def test_allow_shrink_flag_is_off_by_default_in_both_entry_points():
    import sync_business_data
    import run_business_etl as run_module

    assert sync_business_data.parse_args([]).allow_shrink is False
    assert sync_business_data.parse_args(["--allow-shrink"]).allow_shrink is True
    assert run_module.parse_args([]).allow_shrink is False
    assert run_module.parse_args(["--allow-shrink"]).allow_shrink is True


@pytest.mark.asyncio
async def test_run_sync_passes_allow_shrink_and_tolerates_cache_failure(monkeypatch):
    import sync_business_data

    calls = {}

    class FakeUseCase:
        async def sync_all(self, **kwargs):
            calls.update(kwargs)
            return {"invoices": 1}

    class FakeClient:
        closed = False

        async def close(self):
            FakeClient.closed = True

    class FakeContainer:
        def sync_business_data_use_case(self):
            return FakeUseCase()

        def cache_service(self):
            raise ConnectionError("redis down")

        def postgres_client(self):
            return FakeClient()

    monkeypatch.setattr(sync_business_data, "container", FakeContainer())

    result = await sync_business_data.run_sync({"customer_df": "c"}, allow_shrink=True)

    assert result == {"invoices": 1}
    assert calls == {
        "customer_df": "c", "allow_shrink": True, "entrypoint": "sync_business_data",
    }
    assert FakeClient.closed


def test_refused_snapshot_never_overwrites_the_last_good_files(tmp_path):
    from etl_business.job import promote_snapshots, staged_snapshot_dir

    live = tmp_path / "Cong_no.xlsx"
    live.write_text("last good", encoding="utf-8")

    with pytest.raises(RuntimeError):
        with staged_snapshot_dir(tmp_path) as staging:
            (staging / "Cong_no.xlsx").write_text("truncated", encoding="utf-8")
            raise RuntimeError("sync refused the snapshot")

    assert live.read_text(encoding="utf-8") == "last good"
    assert [path.name for path in tmp_path.iterdir()] == ["Cong_no.xlsx"]  # staging removed

    with staged_snapshot_dir(tmp_path) as staging:
        staged = staging / "Cong_no.xlsx"
        staged.write_text("new", encoding="utf-8")
        assert promote_snapshots((staged,), tmp_path) == (live,)
    assert live.read_text(encoding="utf-8") == "new"
    assert [path.name for path in tmp_path.iterdir()] == ["Cong_no.xlsx"]
