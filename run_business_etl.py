"""Stable one-command entry point for Task Scheduler or another cron runner."""

import argparse
import asyncio
import json

from etl_business.job import run_business_etl
from etl_business.shop_data_extractor.config import load_settings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the business ETL once")
    parser.add_argument(
        "--allow-shrink",
        action="store_true",
        help=(
            "Permit soft-deleting records when a snapshot is empty or much smaller "
            "than the active data (refused by default)."
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    result = asyncio.run(
        run_business_etl(load_settings(), allow_shrink=args.allow_shrink)
    )
    print(json.dumps(result, ensure_ascii=False, default=str))
