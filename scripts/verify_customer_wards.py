import asyncio
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from config.config_manager import get_settings


async def main() -> None:
    settings = get_settings()
    aliases = json.loads(
        Path(settings.etl.customer_ward_aliases_path).read_text(encoding="utf-8")
    )
    canonical = sorted(set(aliases) - {"Khác"}) + ["Khác"]
    engine = create_async_engine(settings.database.url)
    query = text(
        """
        SELECT
          count(*) FILTER (
            WHERE deleted_at IS NULL AND ward_name IS NULL
              AND nullif(btrim(address_detail), '') IS NOT NULL
          ) AS customers_null_with_address,
          count(*) FILTER (
            WHERE deleted_at IS NULL AND ward_name IS NULL
          ) AS customers_null_total,
          count(*) FILTER (
            WHERE deleted_at IS NULL
              AND ward_name IS NOT NULL
              AND NOT (ward_name = ANY(:canonical))
          ) AS customers_invalid
        FROM customers
        """
    )
    invoice_query = text(
        """
        SELECT count(*)
        FROM sales_invoices
        WHERE deleted_at IS NULL
          AND customer_ward_name_snapshot IS NOT NULL
          AND NOT (customer_ward_name_snapshot = ANY(:canonical))
        """
    )
    distribution_query = text(
        """
        SELECT coalesce(ward_name, '<NULL>') AS ward_name, count(*) AS total
        FROM customers
        WHERE deleted_at IS NULL
        GROUP BY ward_name
        ORDER BY total DESC, ward_name
        """
    )
    async with engine.connect() as connection:
        customer_counts = (await connection.execute(query, {"canonical": canonical})).mappings().one()
        invoice_invalid = (await connection.execute(invoice_query, {"canonical": canonical})).scalar_one()
        distribution = [dict(row) for row in (await connection.execute(distribution_query)).mappings()]
    await engine.dispose()
    print(json.dumps({**customer_counts, "invoices_invalid": invoice_invalid, "distribution": distribution}))


if __name__ == "__main__":
    asyncio.run(main())
