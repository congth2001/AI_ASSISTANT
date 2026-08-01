import pandas as pd
import asyncio
from pathlib import Path

from config.config_manager import get_settings
from config.container import container

if __name__ == "__main__":
    settings = get_settings()
    container.config.from_dict(settings.model_dump())

    data_dir = Path(__file__).resolve().parent / "data" / "documents"
    df_invoice_customers = pd.read_excel(data_dir / "Khach_hang.xlsx")
    df_invoice_goods = pd.read_excel(data_dir / "Hang_hoa.xlsx")

    use_case = container.sync_business_data_use_case()

    async def main():
        try:
            result = await use_case.sync_all(
                df_invoice_customers,
                df_invoice_goods,
            )
            print(result)
        finally:
            await container.postgres_client().close()

    asyncio.run(main())
