from __future__ import annotations

from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from config.config_manager import ConfigManager
from config.container import container
from etl_business.normalization import (
    load_customer_ward_aliases,
    load_product_aliases,
)
from etl_business.pipeline import build_business_snapshots
from etl_business.shop_data_extractor.access import open_mdb_source, resolve_mdb_source
from etl_business.shop_data_extractor.extractor import extract_all
from etl_business.shop_data_extractor.reports import export_excel, export_manifest_csv


async def run_business_etl(config: dict) -> dict[str, Any]:
    """Run the cron-safe, idempotent MDB-to-PostgreSQL pipeline once."""
    runtime = config["_runtime"]
    Path(runtime["lock_path"]).parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(runtime["lock_path"], timeout=0)
    try:
        with lock:
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
            customer_path, goods_path, debt_path, returns_path, return_lines_path = snapshots.write_excel(
                runtime["snapshot_dir"]
            )

            app_settings = ConfigManager(
                runtime["project_config_path"]
            ).get_settings()
            container.config.from_dict(app_settings.model_dump())
            try:
                sync_result = await container.sync_business_data_use_case().sync_all(
                    snapshots.customers,
                    snapshots.goods,
                    snapshots.debt_transactions,
                    snapshots.sales_returns,
                    snapshots.sales_return_lines,
                )
            finally:
                await container.postgres_client().close()

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
    except Timeout as exc:
        raise RuntimeError("Another business ETL job is already running") from exc
