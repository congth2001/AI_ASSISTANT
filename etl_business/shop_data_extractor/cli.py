from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .config import load_settings
from .access import open_mdb_source
from .profiler import build_profile
from .extractor import extract_all
from .reports import export_excel, export_manifest_csv
from etl_business.pipeline import build_business_snapshots
from etl_business.job import run_business_etl
from etl_business.normalization import load_customer_ward_aliases

def require_mdb(runtime: dict):
    if not runtime["source_path"]:
        raise RuntimeError("etl.source_path is empty. Configure it in config/local.yml.")

def cmd_inspect(cfg: dict):
    runtime = cfg["_runtime"]
    require_mdb(runtime)
    with open_mdb_source(
        runtime["source_path"], runtime["mdb_password"], runtime["mdb_member"]
    ) as conn:
        profile = build_profile(conn, runtime["output_dir"])
    print(f"Schema profile created: {runtime['output_dir']}")
    print(f"Tables discovered: {len(profile['tables'])}")

def cmd_extract(cfg: dict):
    runtime = cfg["_runtime"]
    require_mdb(runtime)
    with open_mdb_source(
        runtime["source_path"], runtime["mdb_password"], runtime["mdb_member"]
    ) as conn:
        datasets, manifest = extract_all(conn, cfg, runtime["output_dir"])

    xlsx = export_excel(datasets, manifest, runtime["output_dir"])
    manifest_csv = export_manifest_csv(manifest, runtime["output_dir"])

    success = sum(1 for x in manifest if x.get("status") == "SUCCESS")
    failed = sum(1 for x in manifest if x.get("status") == "FAILED")
    skipped = sum(1 for x in manifest if x.get("status") == "SKIPPED")

    print(f"Excel: {xlsx}")
    print(f"Manifest: {manifest_csv}")
    print(f"Datasets: success={success}, failed={failed}, skipped={skipped}")

    if failed:
        sys.exit(2)

    if all(name in datasets for name in ("customers", "sales", "sale_items", "products")):
        paths = build_business_snapshots(
            datasets,
            customer_ward_aliases=load_customer_ward_aliases(
                runtime["customer_ward_aliases_path"]
            ),
            opening_balance_date=runtime["opening_balance_date"],
        ).write_excel(runtime["snapshot_dir"])
        print(f"Application snapshots: {paths[0]}, {paths[1]}, {paths[2]}")


def cmd_run(cfg: dict):
    require_mdb(cfg["_runtime"])
    result = asyncio.run(run_business_etl(cfg))
    print(json.dumps(result, ensure_ascii=False, default=str))

def main():
    parser = argparse.ArgumentParser(description="Extract iShopman MDB to CSV/Excel")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect", help="Inspect MDB schema and samples")
    sub.add_parser("extract", help="Extract configured business datasets")
    sub.add_parser("run", help="Extract, normalize, and sync to PostgreSQL")
    parser.add_argument("--config", help="Path to extraction YAML")
    args = parser.parse_args()

    cfg = load_settings(args.config)
    if args.command == "inspect":
        cmd_inspect(cfg)
    elif args.command == "extract":
        cmd_extract(cfg)
    elif args.command == "run":
        cmd_run(cfg)

if __name__ == "__main__":
    main()
