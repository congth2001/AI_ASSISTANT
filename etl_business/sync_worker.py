"""Run one business-data sync for the admin data-sync screen.

Started by ``SubprocessSyncRunner`` (``src/modules/data_sync``) as
``python -m etl_business.sync_worker --source mdb|snapshot [--allow-shrink]`` from
``backend/``. The last stdout line is ``DATA_SYNC_RESULT <json>``:

- ``{"ok": true, "result": {...sync summary...}}`` with exit code 0, or
- ``{"ok": false, "error_code": "...", "message": "..."}`` with exit code 1.

Tracebacks go to stderr (logged by the backend), never into the message.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from typing import Any

from etl_business.runtime import ALREADY_RUNNING_MESSAGE
from src.common.errors import ApplicationError

from src.modules.data_sync.domain.models.sync_job import ENTRYPOINT_BY_SOURCE

RESULT_PREFIX = "DATA_SYNC_RESULT "
ENTRYPOINTS = {source.value: name for source, name in ENTRYPOINT_BY_SOURCE.items()}
# Absolute server paths in the ETL result are not shown on the admin screen.
_PATH_KEYS = frozenset({
    "source", "customer_snapshot", "goods_snapshot", "debt_snapshot",
    "returns_snapshot", "return_lines_snapshot",
})
_MESSAGE_MAX_CHARS = 1500
ALREADY_RUNNING_TEXT = (
    "Đang có một tiến trình đồng bộ khác chạy (lịch tự động hoặc dòng lệnh). "
    "Thử lại sau khi tiến trình đó kết thúc."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one business-data sync and report JSON")
    parser.add_argument("--source", choices=sorted(ENTRYPOINTS), required=True)
    parser.add_argument("--allow-shrink", action="store_true")
    return parser.parse_args(argv)


async def run_source(source: str, allow_shrink: bool) -> dict[str, Any]:
    entrypoint = ENTRYPOINTS[source]
    if source == "mdb":
        from etl_business.job import run_business_etl
        from etl_business.shop_data_extractor.config import load_settings

        return await run_business_etl(
            load_settings(), allow_shrink=allow_shrink, entrypoint=entrypoint
        )

    from config.config_manager import get_settings
    from config.container import container
    from etl_business.runtime import exclusive_etl_lock, resolve_lock_path
    from etl_business.snapshot_columns import read_snapshot_directory
    from sync_business_data import run_sync, snapshot_directory

    settings = get_settings()
    container.config.from_dict(settings.to_container_config())
    with exclusive_etl_lock(resolve_lock_path(settings.etl.lock_path)):
        # Same directory the MDB ETL promotes into, so both sources stay consistent.
        snapshots = read_snapshot_directory(snapshot_directory(settings))
        return await run_sync(snapshots, allow_shrink=allow_shrink, entrypoint=entrypoint)


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key not in _PATH_KEYS}


def describe_failure(error: BaseException) -> dict[str, Any]:
    if isinstance(error, RuntimeError) and str(error) == ALREADY_RUNNING_MESSAGE:
        code, message = "already_running", ALREADY_RUNNING_TEXT
    elif isinstance(error, ApplicationError):
        code, message = error.code, error.message
    elif isinstance(error, ConnectionError):
        code = "connection_failed"
        message = f"Không kết nối được cơ sở dữ liệu hoặc dịch vụ cần thiết ({error})."
    elif isinstance(error, FileNotFoundError):
        code, message = "file_not_found", f"Không tìm thấy file: {error.filename or error}"
    elif isinstance(error, (RuntimeError, OSError, ValueError)):
        # ETL extraction failures (dataset, table, driver error) arrive as RuntimeError.
        code, message = "sync_failed", str(error) or type(error).__name__
    else:
        code = "unexpected"
        message = f"Lỗi không xác định ({type(error).__name__}). Xem log backend để biết chi tiết."
    return {"ok": False, "error_code": code, "message": message[:_MESSAGE_MAX_CHARS]}


def emit(report: dict[str, Any]) -> None:
    print(RESULT_PREFIX + json.dumps(report, ensure_ascii=False, default=str), flush=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = asyncio.run(run_source(args.source, args.allow_shrink))
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        emit(describe_failure(error))
        return 1
    emit({"ok": True, "result": summarize(result)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
