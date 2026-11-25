from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from config.config_manager import ConfigManager
from config.container import container
from etl_business.normalization import (
    load_customer_ward_aliases,
    load_product_aliases,
)
from etl_business.pipeline import build_business_snapshots
from etl_business.runtime import exclusive_etl_lock, invalidate_chat_response_cache
from etl_business.shop_data_extractor.access import open_mdb_source, resolve_mdb_source
from etl_business.shop_data_extractor.extractor import extract_all
from etl_business.shop_data_extractor.reports import export_excel, export_manifest_csv


@contextmanager
def staged_snapshot_dir(snapshot_dir: str | Path) -> Iterator[Path]:
    """Temporary directory next to ``snapshot_dir`` (same volume, so ``os.replace`` is atomic).

    Snapshots are written here first and only promoted after PostgreSQL accepted them,
    so a snapshot refused by the sync guard never overwrites the last good files.
    """
    destination = Path(snapshot_dir)
    destination.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=destination))
    try:
        yield staging
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def promote_snapshots(staged: tuple[Path, ...], snapshot_dir: str | Path) -> tuple[Path, ...]:
    destination = Path(snapshot_dir)
    promoted = []
    for path in staged:
        target = destination / path.name
        os.replace(path, target)
        promoted.append(target)
    return tuple(promoted)


async def run_business_etl(config: dict, *, allow_shrink: bool = False) -> dict[str, Any]:
    """Run the cron-safe, idempotent MDB-to-PostgreSQL pipeline once.

    ``allow_shrink`` lets the sync soft-delete records when the new snapshot is
    empty or much smaller than the active data; by default such a snapshot is
    refused (see ``SyncBusinessDataUseCase``).
    """
    runtime = config["_runtime"]
    with exclusive_etl_lock(runtime["lock_path"]):
        selected_source = resolve_mdb_source(runtime["source_path"])
        with open_mdb_source(
            str(selected_source),
            runtime["mdb_password"],
            runtime["mdb_member"],
        ) as connection:
            datasets, manifest = extract_all(
                connection, config, runtime["output_dir"]
            )

        export_excel(datasets, manifest, runtime["output_dir"])
        export_manifest_csv(manifest, runtime["output_dir"])
        failures = [row for row in manifest if row.get("status") == "FAILED"]
        if failures:
            names = ", ".join(str(row.get("dataset")) for row in failures)
            raise RuntimeError(f"Extraction failed for datasets: {names}")

        aliases = load_product_aliases(runtime["product_aliases_path"])
        ward_aliases = load_customer_ward_aliases(
            runtime["customer_ward_aliases_path"]
        )
        snapshots = build_business_snapshots(
            datasets,
            aliases,
            ward_aliases,
            runtime["opening_balance_date"],
        )
        app_settings = ConfigManager(
            runtime["project_config_path"]
        ).get_settings()
        container.config.from_dict(app_settings.to_container_config())
        with staged_snapshot_dir(runtime["snapshot_dir"]) as staging:
            # Write before syncing so disk errors surface early, but keep the files staged
            # until the sync (and its shrink guard) has committed.
            staged = snapshots.write_excel(staging)
            try:
                sync_result = await container.sync_business_data_use_case().sync_all(
                    **snapshots.sync_arguments(), allow_shrink=allow_shrink, entrypoint="etl_job"
                )
                await invalidate_chat_response_cache(container.cache_service)
            finally:
                await container.postgres_client().close()
            (
                customer_path, goods_path, debt_path, returns_path, return_lines_path
            ) = promote_snapshots(staged, runtime["snapshot_dir"])

        return {
            "status": "SUCCESS",
            "source": str(selected_source),
            "aliases": len(aliases),
            "ward_aliases": len(ward_aliases),
            "customer_snapshot": str(customer_path),
            "goods_snapshot": str(goods_path),
            "debt_snapshot": str(debt_path),
            "returns_snapshot": str(returns_path),
            "return_lines_snapshot": str(return_lines_path),
            **sync_result,
        }
