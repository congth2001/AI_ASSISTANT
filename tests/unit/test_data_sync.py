"""Admin data-sync module: use case, subprocess runner, worker report and HTTP API."""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from src.common.domain.time import VIETNAM_TIMEZONE
from src.modules.data_sync.application.use_cases.data_sync_use_case import (
    SHUTDOWN_MESSAGE,
    STALE_JOB_MESSAGE,
    DataSyncUseCase,
)
from src.modules.data_sync.domain.errors import (
    SyncJobAlreadyRunningError,
    SyncJobNotFoundError,
    SyncSnapshotStaleError,
    SyncSourceUnavailableError,
)
from src.modules.data_sync.domain.models.sync_job import (
    EXTRACTION_ENTRYPOINTS,
    WORKER_CRASHED,
    WORKER_INTERRUPTED,
    WORKER_TIMEOUT,
    SyncJob,
    SyncJobPage,
    SyncJobStatus,
    SyncRunOutcome,
    SyncSource,
)
from src.modules.data_sync.domain.ports.i_sync_runner import ISyncRunner
from src.modules.data_sync.domain.repositories.i_etl_run_history import IEtlRunHistory
from src.modules.data_sync.domain.repositories.i_sync_job_repository import ISyncJobRepository
from src.modules.data_sync.infrastructure.runners.subprocess_sync_runner import (
    RESULT_PREFIX,
    SNAPSHOT_FILES,
    SubprocessSyncRunner,
    outcome_from_report,
    parse_worker_report,
)

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=VIETNAM_TIMEZONE)


class MemoryRepository(ISyncJobRepository):
    def __init__(self):
        self.jobs: dict[str, SyncJob] = {}
        self.touched: list[str] = []

    async def create_running(self, job):
        if any(item.is_running for item in self.jobs.values()):
            raise SyncJobAlreadyRunningError()
        created = SyncJob(
            id=f"job-{len(self.jobs) + 1}", source=job.source, status=SyncJobStatus.RUNNING,
            allow_shrink=job.allow_shrink, created_at=job.started_at,
            heartbeat_at=job.started_at, triggered_by_id=job.triggered_by_id,
        )
        self.jobs[created.id] = created
        return created

    async def touch(self, job_id, at):
        self.touched.append(job_id)
        self.jobs[job_id] = replace(self.jobs[job_id], heartbeat_at=at)

    async def finish(self, job_id, *, status, finished_at, result, error_code, error_message):
        job = self.jobs[job_id]
        if job.is_running:
            self.jobs[job_id] = replace(
                job, status=status, finished_at=finished_at, result=result,
                error_code=error_code, error_message=error_message,
            )

    async def fail_stale(self, heartbeat_before, *, finished_at, error_code, message):
        stale = [j for j in self.jobs.values() if j.is_running and j.heartbeat_at < heartbeat_before]
        for job in stale:
            self.jobs[job.id] = replace(
                job, status=SyncJobStatus.FAILED, finished_at=finished_at,
                error_code=error_code, error_message=message,
            )
        return len(stale)

    async def get(self, job_id):
        return self.jobs.get(job_id)

    async def get_running(self):
        return next((j for j in self.jobs.values() if j.is_running), None)

    async def list_recent(self, limit, offset):
        items = sorted(self.jobs.values(), key=lambda j: (j.created_at, j.id), reverse=True)
        return SyncJobPage(items[offset:offset + limit], len(items) > offset + limit)


class FakeRunner(ISyncRunner):
    def __init__(
        self, outcome=None, error=None, gate: asyncio.Event | None = None, unavailable=None,
        snapshot_at: datetime | None = None,
    ):
        self.outcome = outcome or SyncRunOutcome.success({"invoices": 3})
        self.error = error
        self.gate = gate
        self.unavailable = unavailable or {}
        self.snapshot_at = snapshot_at
        self.calls = []

    def snapshot_modified_at(self):
        return self.snapshot_at

    async def run(self, source, *, allow_shrink, timeout_seconds):
        self.calls.append((source, allow_shrink, timeout_seconds))
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return self.outcome

    def unavailable_reason(self, source):
        return self.unavailable.get(source)


class FakeHistory(IEtlRunHistory):
    def __init__(self, finished_at=None):
        self.finished_at = finished_at
        self.asked = []

    async def latest_finished_at(self, entrypoints):
        self.asked.append(entrypoints)
        return self.finished_at


def use_case(repo, runner, history=None, **kwargs):
    kwargs.setdefault("clock", lambda: NOW)
    return DataSyncUseCase(repo, runner, history or FakeHistory(), timeout_seconds=600, **kwargs)


@pytest.mark.asyncio
async def test_start_runs_the_sync_in_background_and_records_success():
    repo, runner = MemoryRepository(), FakeRunner()
    service = use_case(repo, runner)

    job = await service.start(SyncSource.SNAPSHOT, allow_shrink=True, triggered_by_id="admin-1")
    assert job.status is SyncJobStatus.RUNNING
    await service.wait_idle()

    finished = await service.get_job(job.id)
    assert finished.status is SyncJobStatus.SUCCEEDED
    assert finished.result == {"invoices": 3}
    assert finished.finished_at == NOW
    assert runner.calls == [(SyncSource.SNAPSHOT, True, 600)]


@pytest.mark.asyncio
async def test_failed_and_crashed_runs_are_recorded_as_failed():
    repo = MemoryRepository()
    failing = use_case(repo, FakeRunner(SyncRunOutcome.failure("snapshot_shrink", "too small")))
    job = await failing.start(SyncSource.MDB, allow_shrink=False, triggered_by_id=None)
    await failing.wait_idle()
    assert (repo.jobs[job.id].status, repo.jobs[job.id].error_code) == (SyncJobStatus.FAILED, "snapshot_shrink")

    crashing = use_case(repo, FakeRunner(error=OSError("cannot spawn")))
    job = await crashing.start(SyncSource.MDB, allow_shrink=False, triggered_by_id=None)
    await crashing.wait_idle()
    assert repo.jobs[job.id].error_code == WORKER_CRASHED
    assert "cannot spawn" not in repo.jobs[job.id].error_message


@pytest.mark.asyncio
async def test_only_one_job_runs_at_a_time():
    gate = asyncio.Event()
    service = use_case(MemoryRepository(), FakeRunner(gate=gate))
    await service.start(SyncSource.MDB, allow_shrink=False, triggered_by_id=None)

    with pytest.raises(SyncJobAlreadyRunningError):
        await service.start(SyncSource.SNAPSHOT, allow_shrink=False, triggered_by_id=None)
    status = await service.get_status()
    assert status.running_job is not None and status.last_job == status.running_job

    gate.set()
    await service.wait_idle()
    assert (await service.get_status()).running_job is None


@pytest.mark.asyncio
async def test_unavailable_source_is_refused_before_creating_a_job():
    repo = MemoryRepository()
    runner = FakeRunner(unavailable={SyncSource.MDB: "chưa cấu hình"})
    service = use_case(repo, runner)

    with pytest.raises(SyncSourceUnavailableError, match="chưa cấu hình"):
        await service.start(SyncSource.MDB, allow_shrink=False, triggered_by_id=None)
    assert repo.jobs == {}
    status = await service.get_status()
    assert [(s.source, s.available) for s in status.sources] == [
        (SyncSource.MDB, False), (SyncSource.SNAPSHOT, True),
    ]


@pytest.mark.asyncio
async def test_job_without_heartbeat_is_failed_so_it_no_longer_blocks():
    repo = MemoryRepository()
    clock = {"now": NOW}
    lost = use_case(repo, FakeRunner(gate=asyncio.Event()), clock=lambda: clock["now"])
    job = await lost.start(SyncSource.MDB, allow_shrink=False, triggered_by_id=None)
    # Simulate a backend restart: the watching task is gone, no more heartbeats.
    for task in list(lost._tasks):
        task.cancel()
    await asyncio.sleep(0)
    repo.jobs[job.id] = replace(repo.jobs[job.id], status=SyncJobStatus.RUNNING, heartbeat_at=NOW)

    clock["now"] = NOW + timedelta(minutes=5)
    fresh = use_case(repo, FakeRunner(), clock=lambda: clock["now"])
    restarted = await fresh.start(SyncSource.SNAPSHOT, allow_shrink=False, triggered_by_id=None)
    await fresh.wait_idle()

    assert repo.jobs[job.id].status is SyncJobStatus.FAILED
    assert repo.jobs[job.id].error_message == STALE_JOB_MESSAGE
    assert repo.jobs[restarted.id].status is SyncJobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_heartbeat_keeps_a_long_job_alive():
    repo = MemoryRepository()
    gate = asyncio.Event()
    service = use_case(repo, FakeRunner(gate=gate), heartbeat_seconds=0.01, stale_after_seconds=0.05)
    job = await service.start(SyncSource.MDB, allow_shrink=False, triggered_by_id=None)
    await asyncio.sleep(0.05)
    gate.set()
    await service.wait_idle()
    assert job.id in repo.touched


@pytest.mark.asyncio
async def test_shutdown_records_running_job_as_interrupted():
    repo = MemoryRepository()
    service = use_case(repo, FakeRunner(gate=asyncio.Event()))
    job = await service.start(SyncSource.MDB, allow_shrink=False, triggered_by_id=None)
    await asyncio.sleep(0)

    await service.shutdown()

    assert repo.jobs[job.id].status is SyncJobStatus.FAILED
    assert (repo.jobs[job.id].error_code, repo.jobs[job.id].error_message) == (
        WORKER_INTERRUPTED, SHUTDOWN_MESSAGE,
    )


@pytest.mark.asyncio
async def test_snapshot_older_than_last_extraction_needs_confirmation():
    repo = MemoryRepository()
    history = FakeHistory(finished_at=NOW)
    runner = FakeRunner(snapshot_at=NOW - timedelta(days=90))
    service = use_case(repo, runner, history)

    status = await service.get_status()
    assert status.snapshot.is_stale is True
    assert history.asked[-1] == EXTRACTION_ENTRYPOINTS

    with pytest.raises(SyncSnapshotStaleError, match="cũ hơn lần đồng bộ"):
        await service.start(SyncSource.SNAPSHOT, allow_shrink=False, triggered_by_id=None)
    assert repo.jobs == {}

    # The MDB source writes fresh snapshots, so it is never blocked by stale files.
    job = await service.start(SyncSource.MDB, allow_shrink=False, triggered_by_id=None)
    await service.wait_idle()
    confirmed = await service.start(
        SyncSource.SNAPSHOT, allow_shrink=False, triggered_by_id=None, allow_stale_snapshot=True
    )
    await service.wait_idle()
    assert [repo.jobs[j.id].status for j in (job, confirmed)] == [SyncJobStatus.SUCCEEDED] * 2


@pytest.mark.parametrize("files_at,extraction_at,stale", [
    (NOW, NOW - timedelta(minutes=1), False),   # files promoted by the last extraction
    (None, NOW, False),                          # files missing: the source is unavailable instead
    (NOW, None, False),                          # never extracted: nothing newer to lose
    (NOW - timedelta(seconds=1), NOW, True),
])
def test_snapshot_staleness_rule(files_at, extraction_at, stale):
    from src.modules.data_sync.domain.models.sync_job import SnapshotStatus

    assert SnapshotStatus(files_at, extraction_at).is_stale is stale


@pytest.mark.asyncio
async def test_unknown_job_is_not_found():
    with pytest.raises(SyncJobNotFoundError):
        await use_case(MemoryRepository(), FakeRunner()).get_job("missing")


# --- worker report parsing -------------------------------------------------------------

def test_report_is_the_last_prefixed_line_and_ignores_progress_output():
    stdout = "\n".join([
        "Extracting customers...",
        RESULT_PREFIX + json.dumps({"ok": False, "error_code": "old"}),
        RESULT_PREFIX + json.dumps({"ok": True, "result": {"invoices": 2}}),
        "",
    ])
    assert parse_worker_report(stdout) == {"ok": True, "result": {"invoices": 2}}
    assert parse_worker_report("no report") is None
    assert parse_worker_report(RESULT_PREFIX + "{broken") is None


def test_outcome_requires_ok_report_and_zero_exit_code():
    assert outcome_from_report({"ok": True, "result": {"a": 1}}, 0) == SyncRunOutcome.success({"a": 1})
    failed = outcome_from_report({"ok": False, "error_code": "snapshot_shrink", "message": "m"}, 1)
    assert (failed.error_code, failed.error_message) == ("snapshot_shrink", "m")
    crashed = outcome_from_report(None, -9)
    assert crashed.error_code == WORKER_CRASHED and "-9" in crashed.error_message


# --- subprocess runner -----------------------------------------------------------------

class ScriptRunner(SubprocessSyncRunner):
    def __init__(self, tmp_path, script):
        super().__init__(tmp_path, mdb_source_path="")
        self.script = script

    def command(self, source, allow_shrink):
        return [sys.executable, "-c", self.script]


@pytest.mark.asyncio
async def test_runner_reads_worker_report_from_child_process(tmp_path):
    report = json.dumps({"ok": True, "result": {"khách": "Nguyễn"}}, ensure_ascii=False)
    script = f"import sys; print('progress'); print({RESULT_PREFIX + report!r})"
    outcome = await ScriptRunner(tmp_path, script).run(
        SyncSource.SNAPSHOT, allow_shrink=False, timeout_seconds=60
    )
    assert outcome == SyncRunOutcome.success({"khách": "Nguyễn"})


@pytest.mark.asyncio
async def test_runner_kills_child_after_timeout(tmp_path):
    outcome = await ScriptRunner(tmp_path, "import time; time.sleep(30)").run(
        SyncSource.SNAPSHOT, allow_shrink=False, timeout_seconds=1
    )
    assert outcome.error_code == WORKER_TIMEOUT


@pytest.mark.asyncio
async def test_runner_reports_a_crash_without_report(tmp_path):
    outcome = await ScriptRunner(tmp_path, "raise SystemExit(3)").run(
        SyncSource.SNAPSHOT, allow_shrink=False, timeout_seconds=60
    )
    assert outcome.error_code == WORKER_CRASHED and "3" in outcome.error_message


def test_runner_reads_the_configured_snapshot_directory(tmp_path):
    import os

    custom = tmp_path / "snapshots"
    custom.mkdir()
    runner = SubprocessSyncRunner(tmp_path, snapshot_dir="snapshots")
    assert runner.snapshot_dir == custom
    assert "thiếu file trong snapshots:" in runner.unavailable_reason(SyncSource.SNAPSHOT)
    assert runner.snapshot_modified_at() is None

    for index, name in enumerate(SNAPSHOT_FILES):
        (custom / name).write_bytes(b"")
        os.utime(custom / name, (1_700_000_000 + index, 1_700_000_000 + index))
    assert runner.unavailable_reason(SyncSource.SNAPSHOT) is None
    oldest = runner.snapshot_modified_at()
    assert oldest.timestamp() == 1_700_000_000 and oldest.utcoffset() == timedelta(hours=7)

    absolute = SubprocessSyncRunner(tmp_path / "elsewhere", snapshot_dir=str(custom))
    assert absolute.snapshot_dir == custom


def test_promoted_snapshots_carry_the_promotion_time(tmp_path):
    import os
    import time

    from etl_business.job import promote_snapshots

    staged = tmp_path / "staging" / "Cong_no.xlsx"
    staged.parent.mkdir()
    staged.write_bytes(b"x")
    os.utime(staged, (1_600_000_000, 1_600_000_000))
    before = time.time() - 1

    (promoted,) = promote_snapshots((staged,), tmp_path)

    assert promoted == tmp_path / "Cong_no.xlsx"
    assert promoted.stat().st_mtime >= before


def test_cli_and_worker_read_etl_snapshot_dir(tmp_path):
    from types import SimpleNamespace

    from sync_business_data import snapshot_directory

    settings = SimpleNamespace(etl=SimpleNamespace(snapshot_dir=str(tmp_path)))
    assert snapshot_directory(settings) == tmp_path
    relative = snapshot_directory(SimpleNamespace(etl=SimpleNamespace(snapshot_dir="data/documents")))
    assert relative.parts[-2:] == ("data", "documents") and relative.is_absolute()


def test_runner_availability_and_command(tmp_path):
    runner = SubprocessSyncRunner(tmp_path, mdb_source_path="  ")
    assert "etl.source_path" in runner.unavailable_reason(SyncSource.MDB)
    assert "Khach_hang.xlsx" in runner.unavailable_reason(SyncSource.SNAPSHOT)

    documents = tmp_path / "data" / "documents"
    documents.mkdir(parents=True)
    for name in SNAPSHOT_FILES:
        (documents / name).write_bytes(b"")
    runner = SubprocessSyncRunner(tmp_path, mdb_source_path=r"D:\Backup", python_executable="py")
    assert runner.unavailable_reason(SyncSource.MDB) is None
    assert runner.unavailable_reason(SyncSource.SNAPSHOT) is None
    assert runner.command(SyncSource.MDB, True) == [
        "py", "-m", "etl_business.sync_worker", "--source", "mdb", "--allow-shrink",
    ]


# --- worker CLI ------------------------------------------------------------------------

def test_worker_maps_errors_to_codes_without_tracebacks():
    from etl_business import sync_worker
    from etl_business.runtime import ALREADY_RUNNING_MESSAGE
    from src.modules.sales.domain.errors import SnapshotShrinkError

    shrink = SnapshotShrinkError(
        snapshot_name="Cong_no", snapshot_count=1, active_count=10, threshold_percent=50
    )
    assert sync_worker.describe_failure(shrink)["error_code"] == "snapshot_shrink"
    assert sync_worker.describe_failure(RuntimeError(ALREADY_RUNNING_MESSAGE))["error_code"] == "already_running"
    assert sync_worker.describe_failure(RuntimeError("Extraction failed"))["message"] == "Extraction failed"
    refused = sync_worker.describe_failure(ConnectionRefusedError("[WinError 1225] refused"))
    assert refused["error_code"] == "connection_failed" and "WinError 1225" in refused["message"]
    unexpected = sync_worker.describe_failure(KeyError("secret-detail"))
    assert unexpected["error_code"] == "unexpected" and "secret-detail" not in unexpected["message"]


def test_worker_main_emits_one_report_and_drops_server_paths(monkeypatch, capsys):
    from etl_business import sync_worker

    async def fake_run(source, allow_shrink):
        assert (source, allow_shrink) == ("mdb", True)
        return {"status": "SUCCESS", "source": r"D:\Backup\a.mdb", "goods_snapshot": "x", "invoices": 5}

    monkeypatch.setattr(sync_worker, "run_source", fake_run)
    assert sync_worker.main(["--source", "mdb", "--allow-shrink"]) == 0
    report = parse_worker_report(capsys.readouterr().out)
    assert report == {"ok": True, "result": {"status": "SUCCESS", "invoices": 5}}

    async def failing(source, allow_shrink):
        raise RuntimeError("boom")

    monkeypatch.setattr(sync_worker, "run_source", failing)
    assert sync_worker.main(["--source", "snapshot"]) == 1
    captured = capsys.readouterr()
    assert parse_worker_report(captured.out)["error_code"] == "sync_failed"
    assert "Traceback" in captured.err


# --- HTTP API --------------------------------------------------------------------------

class StubUseCase:
    def __init__(self, error=None):
        self.error = error
        self.started = []
        self.job = SyncJob(
            id="0b9d3f40-5f3e-4c86-9a43-1b2a3c4d5e6f", source=SyncSource.MDB,
            status=SyncJobStatus.RUNNING, allow_shrink=False, created_at=NOW, heartbeat_at=NOW,
            triggered_by_id="admin-1", triggered_by_name="Admin",
        )

    async def start(self, source, *, allow_shrink, triggered_by_id, allow_stale_snapshot=False):
        if self.error:
            raise self.error
        self.started.append((source, allow_shrink, triggered_by_id, allow_stale_snapshot))
        return self.job

    async def get_status(self):
        from src.modules.data_sync.domain.models.sync_job import (
            DataSyncStatus, SnapshotStatus, SyncSourceAvailability,
        )

        return DataSyncStatus(
            sources=[SyncSourceAvailability(SyncSource.MDB, True)],
            running_job=self.job, last_job=self.job, timeout_seconds=600,
            snapshot=SnapshotStatus(NOW - timedelta(days=1), NOW),
        )

    async def list_jobs(self, limit, offset):
        return SyncJobPage([self.job], has_more=False)

    async def get_job(self, job_id):
        if job_id != self.job.id:
            raise SyncJobNotFoundError()
        return self.job

    async def shutdown(self):
        pass


@contextmanager
def client_for(role, stub):
    from config.container import container
    from main import create_app
    from src.modules.auth.presentation.router import get_current_user

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": "admin-1", "role": role}
    with container.data_sync_use_case.override(providers.Object(stub)), TestClient(app) as client:
        yield client


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/data-sync/status"),
    ("GET", "/api/v1/data-sync/jobs"),
    ("POST", "/api/v1/data-sync/jobs"),
])
def test_data_sync_api_is_admin_only(method, path):
    stub = StubUseCase()
    with client_for("staff", stub) as client:
        response = client.request(method, path, json={} if method == "POST" else None)
    assert response.status_code == 403
    assert stub.started == []


def test_admin_starts_a_job_and_reads_it_back():
    stub = StubUseCase()
    with client_for("admin", stub) as client:
        started = client.post(
            "/api/v1/data-sync/jobs",
            json={"source": "snapshot", "allow_shrink": True, "allow_stale_snapshot": True},
        )
        status = client.get("/api/v1/data-sync/status")
        page = client.get("/api/v1/data-sync/jobs?limit=5")
        job = client.get(f"/api/v1/data-sync/jobs/{stub.job.id}")
        missing = client.get("/api/v1/data-sync/jobs/6f5e4d3c-2b1a-4c86-9a43-1b2a3c4d5e6f")
        invalid = client.post("/api/v1/data-sync/jobs", json={"source": "ftp"})

    assert started.status_code == 202
    assert started.json()["triggered_by_name"] == "Admin"
    assert stub.started == [(SyncSource.SNAPSHOT, True, "admin-1", True)]
    assert status.json()["timeout_seconds"] == 600
    assert status.json()["snapshot"]["is_stale"] is True
    assert status.json()["snapshot"]["files_modified_at"].endswith("+07:00")
    assert status.json()["running_job"]["id"] == stub.job.id
    assert page.json()["has_more"] is False and len(page.json()["items"]) == 1
    assert job.json()["status"] == "running"
    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_conflict_and_unavailable_source_map_to_http_errors():
    with client_for("admin", StubUseCase(SyncJobAlreadyRunningError())) as client:
        conflict = client.post("/api/v1/data-sync/jobs", json={})
    with client_for("admin", StubUseCase(SyncSourceUnavailableError(source="mdb", reason="x"))) as client:
        unavailable = client.post("/api/v1/data-sync/jobs", json={})
    stale_error = SyncSnapshotStaleError(
        files_modified_at="21/08/2026 23:06", latest_extraction_at="26/11/2026 20:39"
    )
    with client_for("admin", StubUseCase(stale_error)) as client:
        stale = client.post("/api/v1/data-sync/jobs", json={"source": "snapshot"})
    assert stale.status_code == 409 and "21/08/2026 23:06" in stale.json()["detail"]
    assert conflict.status_code == 409
    assert "Đang có một lượt đồng bộ" in conflict.json()["detail"]
    assert unavailable.status_code == 400
