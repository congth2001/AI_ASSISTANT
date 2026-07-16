import pandas as pd
from typing import Dict, Any
from src.domain.repositories.i_invoice_customer_repository import IInvoiceCustomerRepository
from src.domain.repositories.i_invoice_good_repository import IInvoiceGoodRepository


class SyncBusinessDataUseCase:

    def __init__(
        self,
        invoice_customer_repository: IInvoiceCustomerRepository,
        invoice_good_repository: IInvoiceGoodRepository,
    ):
        self._invoice_customer_repository = invoice_customer_repository
        self._invoice_good_repository = invoice_good_repository

    async def sync_customers(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        df columns: invoice_id, date, customer_name, address_detail,
                    address_village, address_ward, total_amount, debt_amount
        Deduplicates by invoice_id before inserting.
        """
        created = 0
        errors = []

        for _, row in df.iterrows():
            try:
                await self._invoice_customer_repository.create({
                    "invoice_id": str(row["Số phiếu"]),
                    "date": pd.to_datetime(row["Ngày"]),
                    "name": str(row["Khách hàng"]),
                    "address_detail": str(row.get("Địa chỉ")) if pd.notnull(row.get("Địa chỉ")) else None,
                    "address_village": str(row.get("Xóm")) if pd.notnull(row.get("Xóm")) else None,
                    "address_ward": str(row.get("Xã")) if pd.notnull(row.get("Xã")) else None,
                    "total_amount": float(row["Tổng tiền"]),
                    "debt_amount": float(row.get("Ghi nợ")) if pd.notnull(row.get("Ghi nợ")) else None,
                })
                created += 1
            except Exception as e:
                errors.append({"invoice_id": str(row["Số phiếu"]), "error": str(e)})

        return {"created": created, "errors": errors}

    async def sync_goods(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        df columns: invoice_id, good_name, category, unit_type,
                    unit_price, quantity, total_price
        Each row is one good line item.
        """
        created = 0
        errors = []

        for _, row in df.iterrows():
            try:
                await self._invoice_good_repository.create({
                    "invoice_id": str(row["Số phiếu"]),
                    "name": str(row["Tên hàng chuẩn hóa"]),
                    "category": str(row.get("Loại mặt hàng")) if pd.notnull(row.get("Loại mặt hàng")) else None,
                    "unit_type": str(row["ĐVT"]),
                    "unit_price": float(row["Đơn giá"]),
                    "quantity": float(row["Số lượng"]),
                    "total_price": float(row["Thành tiền"]),
                })
                created += 1
            except Exception as e:
                errors.append({"invoice_id": str(row["Số phiếu"]), "error": str(e)})

        return {"created": created, "errors": errors}
