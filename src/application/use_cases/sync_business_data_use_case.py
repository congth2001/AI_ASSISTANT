import re
from decimal import Decimal
from typing import Any, Dict

import pandas as pd

from src.domain.repositories.i_customer_repository import ICustomerRepository
from src.domain.repositories.i_customer_debt_transaction_repository import (
    ICustomerDebtTransactionRepository,
)
from src.domain.repositories.i_sales_invoice_line_repository import (
    ISalesInvoiceLineRepository,
)
from src.domain.repositories.i_sales_invoice_repository import (
    ISalesInvoiceRepository,
)
from src.domain.repositories.i_sales_return_repository import ISalesReturnRepository


class SyncBusinessDataUseCase:
    """Idempotently synchronize the two Excel snapshots into sales tables."""

    CUSTOMER_COLUMNS = {
        "Ngày",
        "Số phiếu",
        "Khách hàng",
        "Tổng tiền",
        "Ghi nợ",
    }
    LINE_COLUMNS = {
        "Số phiếu",
        "Tên hàng chuẩn hóa",
        "Loại mặt hàng",
        "ĐVT",
        "Đơn giá",
        "Số lượng",
        "Thành tiền",
    }
    DEBT_COLUMNS = {
        "source_type",
        "source_id",
        "occurred_at",
        "customer_name",
        "amount",
    }
    RETURN_COLUMNS = {
        "source_id", "return_number", "occurred_at", "return_total_amount",
        "customer_name",
    }
    RETURN_LINE_COLUMNS = {
        "source_id", "source_line_id", "product_name", "unit_name",
        "unit_price", "quantity", "line_amount",
    }

    def __init__(
        self,
        customer_repository: ICustomerRepository,
        sales_invoice_repository: ISalesInvoiceRepository,
        sales_invoice_line_repository: ISalesInvoiceLineRepository,
        customer_debt_transaction_repository: ICustomerDebtTransactionRepository | None = None,
        sales_return_repository: ISalesReturnRepository | None = None,
    ):
        self._customer_repository = customer_repository
        self._sales_invoice_repository = sales_invoice_repository
        self._sales_invoice_line_repository = sales_invoice_line_repository
        self._customer_debt_transaction_repository = customer_debt_transaction_repository
        self._sales_return_repository = sales_return_repository

    async def sync_all(
        self,
        customer_df: pd.DataFrame,
        goods_df: pd.DataFrame,
        debt_df: pd.DataFrame | None = None,
        returns_df: pd.DataFrame | None = None,
        return_lines_df: pd.DataFrame | None = None,
    ) -> Dict[str, Any]:
        invoice_result, invoice_ids = await self._upsert_invoices(customer_df)
        line_result = await self._upsert_lines(goods_df, invoice_ids)
        result = {
            **invoice_result,
            "lines": line_result["lines"],
            "line_invoices": line_result["invoices"],
        }
        if debt_df is not None:
            if self._customer_debt_transaction_repository is None:
                raise RuntimeError("Customer debt transaction repository is not configured")
            result["debt_transactions"] = await self._sync_debt_transactions(debt_df)
        if returns_df is not None:
            if self._sales_return_repository is None:
                raise RuntimeError("Sales return repository is not configured")
            if return_lines_df is None:
                raise ValueError("Sales return lines snapshot is required")
            result["sales_returns"] = await self._sync_sales_returns(
                returns_df, return_lines_df
            )
        if debt_df is not None or returns_df is not None:
            result["customers_deleted"] = (
                await self._customer_repository.soft_delete_unreferenced()
            )
        return result

    async def _sync_sales_returns(
        self, headers_df: pd.DataFrame, lines_df: pd.DataFrame
    ) -> Dict[str, int]:
        self._require_columns(headers_df, self.RETURN_COLUMNS, "sales returns")
        self._require_columns(lines_df, self.RETURN_LINE_COLUMNS, "sales return lines")
        header_columns = [
            "source_id", "return_number", "occurred_at", "return_total_amount",
            "customer_name", "address_detail", "village_name", "ward_name",
        ]
        headers = headers_df[header_columns].drop_duplicates().copy()
        if headers["source_id"].astype(str).duplicated().any():
            raise ValueError("Sales return snapshot has inconsistent duplicate headers")
        if lines_df[["source_id", "source_line_id"]].astype(str).duplicated().any():
            raise ValueError("Sales return snapshot contains duplicate source lines")

        customer_rows: Dict[str, Dict[str, Any]] = {}
        prepared_headers: list[Dict[str, Any]] = []
        for _, row in headers.iterrows():
            customer_name = self._required_text(row["customer_name"], "customer_name")
            village_name = self._optional_text(row.get("village_name"))
            ward_name = self._optional_text(row.get("ward_name"))
            identity_key = self.build_customer_identity_key(customer_name, ward_name, village_name)
            customer_rows[identity_key] = {
                "customer_identity_key": identity_key,
                "customer_name": customer_name,
                "address_detail": self._optional_text(row.get("address_detail")),
                "village_name": village_name,
                "ward_name": ward_name,
            }
            returned_at = pd.to_datetime(row["occurred_at"], errors="raise")
            prepared_headers.append(
                {
                    "source_id": self._required_text(row["source_id"], "source_id"),
                    "return_number": self._required_text(row["return_number"], "return_number"),
                    "returned_at": returned_at.to_pydatetime(),
                    "customer_identity_key": identity_key,
                    "customer_name_snapshot": customer_name,
                    "customer_address_detail_snapshot": self._optional_text(row.get("address_detail")),
                    "customer_village_name_snapshot": village_name,
                    "customer_ward_name_snapshot": ward_name,
                    "return_total_amount": self._decimal(row["return_total_amount"], "return_total_amount"),
                }
            )

        customer_ids = await self._customer_repository.upsert_many(list(customer_rows.values()))
        for row in prepared_headers:
            identity_key = row.pop("customer_identity_key")
            row["customer_id"] = customer_ids[identity_key]

        counters: Dict[str, int] = {}
        prepared_lines: list[Dict[str, Any]] = []
        header_source_ids = {str(value).strip() for value in headers["source_id"]}
        line_source_ids = {str(value).strip() for value in lines_df["source_id"]}
        missing_headers = sorted(line_source_ids - header_source_ids)
        if missing_headers:
            raise ValueError("Sales return lines reference unknown headers: " + ", ".join(missing_headers[:10]))
        for _, row in lines_df.iterrows():
            source_id = self._required_text(row["source_id"], "source_id")
            counters[source_id] = counters.get(source_id, 0) + 1
            prepared_lines.append(
                {
                    "source_id": source_id,
                    "source_line_id": self._required_text(row["source_line_id"], "source_line_id"),
                    "line_number": counters[source_id],
                    "product_name": self._required_text(row["product_name"], "product_name"),
                    "product_category_name": self._optional_text(row.get("product_category_name")),
                    "unit_name": self._required_text(row["unit_name"], "unit_name"),
                    "unit_price": self._decimal(row["unit_price"], "unit_price"),
                    "quantity": self._decimal(row["quantity"], "quantity"),
                    "line_amount": self._decimal(row["line_amount"], "line_amount"),
                }
            )
        return await self._sales_return_repository.sync_snapshot(prepared_headers, prepared_lines)

    async def _sync_debt_transactions(self, df: pd.DataFrame) -> Dict[str, int]:
        self._require_columns(df, self.DEBT_COLUMNS, "debt transactions")
        duplicate = df.duplicated(subset=["source_type", "source_id"], keep=False)
        if duplicate.any():
            raise ValueError("Debt snapshot contains duplicate source keys")

        customer_rows: Dict[str, Dict[str, Any]] = {}
        prepared: list[Dict[str, Any]] = []
        for _, row in df.iterrows():
            customer_name = self._required_text(row["customer_name"], "customer_name")
            village_name = self._optional_text(row.get("village_name"))
            ward_name = self._optional_text(row.get("ward_name"))
            identity_key = self.build_customer_identity_key(
                customer_name, ward_name, village_name
            )
            customer_rows[identity_key] = {
                "customer_identity_key": identity_key,
                "customer_name": customer_name,
                "address_detail": self._optional_text(row.get("address_detail")),
                "village_name": village_name,
                "ward_name": ward_name,
            }
            occurred_at = pd.to_datetime(row["occurred_at"], errors="raise")
            prepared.append(
                {
                    "customer_identity_key": identity_key,
                    "source_type": self._required_text(row["source_type"], "source_type"),
                    "source_id": self._required_text(row["source_id"], "source_id"),
                    "occurred_at": occurred_at.to_pydatetime(),
                    "amount": self._decimal(row["amount"], "amount"),
                }
            )

        customer_ids = await self._customer_repository.upsert_many(list(customer_rows.values()))
        ledger_rows = []
        for row in prepared:
            identity_key = row.pop("customer_identity_key")
            ledger_rows.append({**row, "customer_id": customer_ids[identity_key]})
        return await self._customer_debt_transaction_repository.sync_snapshot(ledger_rows)

    async def _upsert_invoices(
        self, df: pd.DataFrame
    ) -> tuple[Dict[str, int], Dict[str, str]]:
        self._require_columns(df, self.CUSTOMER_COLUMNS, "customers")

        duplicated = df["Số phiếu"].astype(str).str.strip().duplicated(keep=False)
        if duplicated.any():
            examples = (
                df.loc[duplicated, "Số phiếu"]
                .astype(str)
                .str.strip()
                .drop_duplicates()
                .head(5)
                .tolist()
            )
            raise ValueError(
                "Customer snapshot contains duplicate invoice numbers: "
                + ", ".join(examples)
            )

        # Keep the latest snapshot for each provisional customer identity.
        customer_candidates: Dict[str, tuple[pd.Timestamp, Dict[str, Any]]] = {}
        prepared_invoices: list[Dict[str, Any]] = []

        for _, row in df.iterrows():
            invoice_number = self._required_text(row["Số phiếu"], "Số phiếu")
            customer_name = self._required_text(row["Khách hàng"], "Khách hàng")
            issued_at = pd.to_datetime(row["Ngày"], errors="raise")
            if pd.isna(issued_at):
                raise ValueError(f"Invoice {invoice_number} has no issue date")

            address_detail = self._optional_text(row.get("Địa chỉ"))
            village_name = self._optional_text(row.get("Xóm"))
            ward_name = self._optional_text(row.get("Xã"))
            identity_key = self.build_customer_identity_key(
                customer_name,
                ward_name,
                village_name,
            )

            customer_data = {
                "customer_identity_key": identity_key,
                "customer_name": customer_name,
                "address_detail": address_detail,
                "village_name": village_name,
                "ward_name": ward_name,
            }
            timestamp = pd.Timestamp(issued_at)
            current = customer_candidates.get(identity_key)
            if current is None or timestamp > current[0]:
                customer_candidates[identity_key] = (
                    timestamp,
                    customer_data,
                )

            prepared_invoices.append(
                {
                    "invoice_number": invoice_number,
                    "issued_at": timestamp.to_pydatetime(),
                    "customer_identity_key": identity_key,
                    "customer_name_snapshot": customer_name,
                    "customer_address_detail_snapshot": address_detail,
                    "customer_village_name_snapshot": village_name,
                    "customer_ward_name_snapshot": ward_name,
                    "invoice_total_amount": self._decimal(
                        row["Tổng tiền"], "Tổng tiền"
                    ),
                    "debt_delta_amount": self._optional_decimal(
                        row.get("Ghi nợ"), "Ghi nợ"
                    ),
                }
            )

        customer_rows = [candidate[1] for candidate in customer_candidates.values()]
        customer_ids = await self._customer_repository.upsert_many(customer_rows)

        invoice_rows = []
        for row in prepared_invoices:
            identity_key = row.pop("customer_identity_key")
            customer_id = customer_ids.get(identity_key)
            if customer_id is None:
                raise RuntimeError(
                    f"Customer upsert returned no UUID for {identity_key!r}"
                )
            invoice_rows.append({**row, "customer_id": customer_id})

        invoice_ids = await self._sales_invoice_repository.upsert_many(invoice_rows)
        if len(invoice_ids) != len(invoice_rows):
            raise RuntimeError("Invoice upsert did not return an ID for every invoice")

        return (
            {
                "customers": len(customer_rows),
                "invoices": len(invoice_rows),
            },
            invoice_ids,
        )

    async def _upsert_lines(
        self,
        df: pd.DataFrame,
        invoice_ids: Dict[str, str],
    ) -> Dict[str, int]:
        self._require_columns(df, self.LINE_COLUMNS, "goods")
        invoice_numbers = self._invoice_numbers(df)
        missing = sorted(set(invoice_numbers) - set(invoice_ids))
        if missing:
            raise ValueError(
                "Goods snapshot references invoices that do not exist: "
                + ", ".join(missing[:10])
            )

        line_counters: Dict[str, int] = {}
        line_rows: list[Dict[str, Any]] = []

        for _, row in df.iterrows():
            invoice_number = self._required_text(row["Số phiếu"], "Số phiếu")
            line_number = line_counters.get(invoice_number, 0) + 1
            line_counters[invoice_number] = line_number

            line_rows.append(
                {
                    "invoice_id": invoice_ids[invoice_number],
                    "line_number": line_number,
                    "product_name": self._required_text(
                        row["Tên hàng chuẩn hóa"],
                        "Tên hàng chuẩn hóa",
                    ),
                    "product_category_name": self._optional_text(
                        row.get("Loại mặt hàng")
                    ),
                    "unit_name": self._required_text(row["ĐVT"], "ĐVT"),
                    "unit_price": self._decimal(row["Đơn giá"], "Đơn giá"),
                    "quantity": self._decimal(row["Số lượng"], "Số lượng"),
                    "line_amount": self._decimal(row["Thành tiền"], "Thành tiền"),
                }
            )

        target_invoice_ids = list(
            dict.fromkeys(invoice_ids[number] for number in invoice_numbers)
        )
        synced = await self._sales_invoice_line_repository.upsert_snapshot(
            line_rows,
            target_invoice_ids,
        )
        return {
            "lines": synced,
            "invoices": len(target_invoice_ids),
        }

    @staticmethod
    def build_customer_identity_key(
        customer_name: str,
        ward_name: str | None,
        village_name: str | None,
    ) -> str:
        return "|".join(
            SyncBusinessDataUseCase._normalize_identity_component(value)
            for value in (customer_name, ward_name, village_name)
        )

    @staticmethod
    def _normalize_identity_component(value: Any) -> str:
        if value is None or pd.isna(value):
            return ""
        return re.sub(r"\s+", " ", str(value).strip()).lower()

    @staticmethod
    def _required_text(value: Any, column: str) -> str:
        text = SyncBusinessDataUseCase._optional_text(value)
        if not text:
            raise ValueError(f"Column {column!r} contains an empty value")
        return text

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None or pd.isna(value):
            return None
        text = re.sub(r"\s+", " ", str(value).strip())
        return text or None

    @staticmethod
    def _decimal(value: Any, column: str) -> Decimal:
        if value is None or pd.isna(value):
            raise ValueError(f"Column {column!r} contains an empty value")
        return Decimal(str(value))

    @staticmethod
    def _optional_decimal(value: Any, column: str) -> Decimal | None:
        if value is None or pd.isna(value):
            return None
        return SyncBusinessDataUseCase._decimal(value, column)

    @staticmethod
    def _invoice_numbers(df: pd.DataFrame) -> list[str]:
        return list(
            dict.fromkeys(
                SyncBusinessDataUseCase._required_text(value, "Số phiếu")
                for value in df["Số phiếu"]
            )
        )

    @staticmethod
    def _require_columns(
        df: pd.DataFrame,
        required: set[str],
        snapshot_name: str,
    ) -> None:
        missing = sorted(required - set(df.columns))
        if missing:
            raise ValueError(
                f"{snapshot_name} snapshot is missing columns: " + ", ".join(missing)
            )
