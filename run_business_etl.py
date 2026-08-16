"""Stable one-command entry point for Task Scheduler or another cron runner."""

import asyncio
import json

from etl_business.job import run_business_etl
from etl_business.shop_data_extractor.config import load_settings


if __name__ == "__main__":
    result = asyncio.run(run_business_etl(load_settings()))
    print(json.dumps(result, ensure_ascii=False, default=str))
