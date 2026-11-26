"""Run ``etl_business.sync_worker`` in a child process and read its JSON report.

A child process keeps the sync away from the web process: the ETL entry points
configure the global DI container and close the PostgreSQL client when they finish,
and the MDB extraction is blocking ODBC work. The child takes the same file lock as
the cron job and the CLI, so the three can never overlap.

``subprocess.Popen`` + a worker thread is used instead of
``asyncio.create_subprocess_exec`` because uvicorn runs a selector event loop on
Windows when reload is on, and that loop cannot start subprocesses.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from src.common.domain.time import VIETNAM_TIMEZONE
from src.modules.data_sync.domain.models.sync_job import (
    WORKER_CRASHED,
    WORKER_TIMEOUT,
    SyncRunOutcome,
    SyncSource,
)
from src.modules.data_sync.domain.ports.i_sync_runner import ISyncRunner

logger = logging.getLogger(__name__)

# Must match etl_business/sync_worker.py.
RESULT_PREFIX = "DATA_SYNC_RESULT "
WORKER_MODULE = "etl_business.sync_worker"
SNAPSHOT_FILES = (
    "Khach_hang.xlsx", "Hang_hoa.xlsx", "Cong_no.xlsx", "Tra_hang.xlsx", "Chi_tiet_tra_hang.xlsx",
)
_STDERR_LOG_CHARS = 8000
_MESSAGE_MAX_CHARS = 2000


@dataclass(frozen=True)
class _Completed:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool


def parse_worker_report(stdout: str) -> dict | None:
    """The last ``DATA_SYNC_RESULT`` line; earlier output (ETL progress) is ignored."""
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            try:
                report = json.loads(line[len(RESULT_PREFIX):])
            except ValueError:
                return None
            return report if isinstance(report, dict) else None
    return None


def outcome_from_report(report: dict | None, returncode: int | None) -> SyncRunOutcome:
    if report is None:
        return SyncRunOutcome.failure(
            WORKER_CRASHED,
            f"Tiến trình đồng bộ kết thúc bất thường (mã thoát {returncode}). Xem log backend.",
        )
    if report.get("ok") is True and returncode == 0:
        result = report.get("result")
        return SyncRunOutcome.success(result if isinstance(result, dict) else {})
    code = str(report.get("error_code") or WORKER_CRASHED)[:64]
    message = str(report.get("message") or "Đồng bộ thất bại.")[:_MESSAGE_MAX_CHARS]
    return SyncRunOutcome.failure(code, message)


class SubprocessSyncRunner(ISyncRunner):
    def __init__(
        self,
        backend_dir: str | Path,
        mdb_source_path: str = "",
        python_executable: str | None = None,
        snapshot_dir: str | Path = "data/documents",
    ):
        self._backend_dir = Path(backend_dir)
        self._mdb_source_path = (mdb_source_path or "").strip()
        self._python = python_executable or sys.executable
        # etl.snapshot_dir: where the MDB ETL promotes snapshots and the worker reads them.
        path = Path(snapshot_dir or "data/documents").expanduser()
        self._snapshot_dir = path if path.is_absolute() else self._backend_dir / path

    @property
    def snapshot_dir(self) -> Path:
        return self._snapshot_dir

    def _snapshot_dir_label(self) -> str:
        try:
            return self._snapshot_dir.relative_to(self._backend_dir).as_posix()
        except ValueError:
            return str(self._snapshot_dir)

    def unavailable_reason(self, source: SyncSource) -> str | None:
        if source is SyncSource.MDB:
            if not self._mdb_source_path:
                return "chưa cấu hình đường dẫn dữ liệu phần mềm bán hàng (etl.source_path)"
            return None
        missing = [name for name in SNAPSHOT_FILES if not (self._snapshot_dir / name).is_file()]
        if missing:
            return f"thiếu file trong {self._snapshot_dir_label()}: {', '.join(missing)}"
        return None

    def snapshot_modified_at(self) -> datetime | None:
        try:
            oldest = min((self._snapshot_dir / name).stat().st_mtime for name in SNAPSHOT_FILES)
        except OSError:
            return None
        return datetime.fromtimestamp(oldest, tz=VIETNAM_TIMEZONE)

    def command(self, source: SyncSource, allow_shrink: bool) -> list[str]:
        args = [self._python, "-m", WORKER_MODULE, "--source", source.value]
        if allow_shrink:
            args.append("--allow-shrink")
        return args

    async def run(
        self, source: SyncSource, *, allow_shrink: bool, timeout_seconds: int
    ) -> SyncRunOutcome:
        process = self._spawn(self.command(source, allow_shrink))
        try:
            completed = await asyncio.to_thread(_communicate, process, timeout_seconds)
        except asyncio.CancelledError:
            # Backend shutting down: stop the sync. PostgreSQL rolls back its transaction.
            _kill(process)
            raise
        if completed.returncode != 0 or completed.timed_out:
            logger.warning(
                "Data sync worker (%s) exited with %s%s; stderr tail:\n%s",
                source.value, completed.returncode,
                " after timeout" if completed.timed_out else "",
                completed.stderr[-_STDERR_LOG_CHARS:],
            )
        if completed.timed_out:
            minutes = max(1, round(timeout_seconds / 60))
            return SyncRunOutcome.failure(
                WORKER_TIMEOUT,
                f"Đồng bộ chạy quá {minutes} phút nên đã bị dừng; dữ liệu không thay đổi.",
            )
        return outcome_from_report(parse_worker_report(completed.stdout), completed.returncode)

    def _spawn(self, args: Sequence[str]) -> subprocess.Popen:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        return subprocess.Popen(
            list(args),
            cwd=self._backend_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )


def _decode(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace")


def _communicate(process: subprocess.Popen, timeout_seconds: int) -> _Completed:
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        timed_out = False
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        timed_out = True
    return _Completed(process.returncode, _decode(stdout), _decode(stderr), timed_out)


def _kill(process: subprocess.Popen) -> None:
    try:
        process.kill()
    except OSError:
        pass
