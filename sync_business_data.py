import pandas as pd
import asyncio
from config.config_manager import get_settings
from config.container import container

if __name__ == "__main__":
    settings = get_settings()
    container.config.from_dict(settings.model_dump())

    df_invoice_customers = pd.read_excel(r"D:\AI_ASSISTANT\data\documents\Khach_hang.xlsx")
    df_invoice_goods = pd.read_excel(r"D:\AI_ASSISTANT\data\documents\Hang_hoa.xlsx")

    use_case = container.sync_business_data_use_case()

    async def main():
        print(await asyncio.gather(
            use_case.sync_customers(df_invoice_customers),
            use_case.sync_goods(df_invoice_goods),
        ))

    asyncio.run(main())