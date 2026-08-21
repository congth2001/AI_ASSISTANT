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
    df_debt_transactions = pd.read_excel(data_dir / "Cong_no.xlsx")
    df_sales_returns = pd.read_excel(data_dir / "Tra_hang.xlsx")
    df_sales_return_lines = pd.read_excel(data_dir / "Chi_tiet_tra_hang.xlsx")

    use_case = container.sync_business_data_use_case()

    async def main():
        try:
            result = await use_case.sync_all(
                df_invoice_customers,
                df_invoice_goods,
                df_debt_transactions,
                df_sales_returns,
                df_sales_return_lines,
            )
            print(result)
        finally:
            await container.postgres_client().close()

    asyncio.run(main())
