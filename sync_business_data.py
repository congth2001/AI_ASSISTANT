"""Synchronize the five Excel snapshots in ``etl.snapshot_dir`` into PostgreSQL.

The directory defaults to data/documents/, where the business ETL promotes its snapshots.
"""
import argparse
import asyncio
from pathlib import Path

from config.config_manager import get_settings
from config.container import container
from etl_business.runtime import (
    exclusive_etl_lock,
    invalidate_chat_response_cache,
    resolve_backend_path,
    resolve_lock_path,
)
from etl_business.snapshot_columns import read_snapshot_directory



def snapshot_directory(settings) -> Path:
    """Where the business ETL writes its snapshots (``etl.snapshot_dir``)."""
    return resolve_backend_path(settings.etl.snapshot_dir)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-shrink",
        action="store_true",
        help=(
            "Permit soft-deleting records when a snapshot is empty or much smaller "
            "than the active data (refused by default)."
        ),
    )
    return parser.parse_args(argv)


async def run_sync(
    snapshots: dict, *, allow_shrink: bool = False, entrypoint: str = "sync_business_data"
) -> dict:
    """Sync once, then drop cached chat answers (best effort).

    ``entrypoint`` is recorded in ``etl_sync_runs`` (the admin screen passes its own name).
    """
    use_case = container.sync_business_data_use_case()
    try:
        result = await use_case.sync_all(
            **snapshots, allow_shrink=allow_shrink, entrypoint=entrypoint
        )
        await invalidate_chat_response_cache(container.cache_service)
        return result
    finally:
        await container.postgres_client().close()


if __name__ == "__main__":
    args = parse_args()
    settings = get_settings()
    container.config.from_dict(settings.to_container_config())

    # Same lock as run_business_etl.py: a manual sync must not overlap the cron job.
    with exclusive_etl_lock(resolve_lock_path(settings.etl.lock_path)):
        snapshots = read_snapshot_directory(snapshot_directory(settings))
        print(asyncio.run(run_sync(snapshots, allow_shrink=args.allow_shrink)))
