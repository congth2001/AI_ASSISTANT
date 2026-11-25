import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict
from uuid import uuid4

import pandas as pd

from src.modules.sales.domain.repositories.i_customer_repository import ICustomerRepository
from src.modules.sales.domain.models.debt_ledger import (
    DebtSnapshotDiff,
    EtlSyncRun,
    IncomingDebtRow,
)
from src.modules.sales.domain.repositories.i_customer_debt_transaction_repository import (
    ICustomerDebtTransactionRepository,
)
from src.modules.sales.domain.repositories.i_debt_revision_repository import (
    IDebtRevisionRepository,
)
from src.modules.sales.domain.services.debt_snapshot_diff import diff_debt_snapshot
from src.modules.sales.domain.repositories.i_sales_invoice_line_repository import (
    ISalesInvoiceLineRepository,
)
from src.modules.sales.domain.repositories.i_sales_invoice_repository import (
    ISalesInvoiceRepository,
)
from src.modules.sales.domain.repositories.i_sales_return_repository import ISalesReturnRepository
from src.modules.sales.domain.ports.i_unit_of_work import IUnitOfWork, NullUnitOfWork
from src.modules.sales.domain.errors import (
    CustomerIdentityMissingError,
    DebtRepositoryRequiredError,
    DuplicateDebtTransactionsError,
    DuplicateInvoiceNumbersError,
    DuplicateSalesReturnLinesError,
    DuplicateSalesReturnNumbersError,
    EmptySnapshotError,
    IncompleteInvoiceUpsertError,
    InconsistentSalesReturnHeadersError,
    InvalidDatetimeValueError,
    InvalidDebtSourceTypeError,
    InvalidDecimalValueError,
    InvoiceIssueDateRequiredError,
    MissingSnapshotColumnsError,
    RequiredColumnValueError,
    SalesReturnLinesRequiredError,
    SalesReturnRepositoryRequiredError,
    SnapshotShrinkError,
    UnknownInvoiceReferencesError,
    UnknownSalesReturnHeadersError,
)

MONEY_SCALE = 2
QUANTITY_SCALE = 3
NUMERIC_PRECISION = 18
DEBT_SOURCE_TYPES = frozenset({"opening", "sale", "receipt", "sales_return"})
# A snapshot may lose at most this share of the active records before the
# sync refuses to soft-delete the difference without ``allow_shrink``.
DEFAULT_MAX_SNAPSHOT_SHRINK_RATIO = Decimal("0.30")


@dataclass
class _PreparedSnapshots:
    """Fully validated rows; nothing is written until every snapshot is valid."""

    invoice_rows: list[Dict[str, Any]] = field(default_factory=list)
    line_rows: list[Dict[str, Any]] = field(default_factory=list)
    debt_rows: list[Dict[str, Any]] | None = None
    return_rows: list[Dict[str, Any]] | None = None
    return_line_rows: list[Dict[str, Any]] | None = None
    # identity key -> ((authoritative, timestamp), profile)
    profiles: Dict[str, tuple[tuple[int, pd.Timestamp], Dict[str, Any]]] = field(
        default_factory=dict
    )
    invoice_customer_count: int = 0

    def remember_profile(
        self,
        profile: Dict[str, Any],
        timestamp: pd.Timestamp,
        authoritative: bool,
    ) -> None:
        """Invoices decide a customer's profile; other sources only fill gaps.

        Within the same authority the latest timestamp wins, so the result
        does not depend on the order in which sources are processed.
        """
        rank = (1 if authoritative else 0, timestamp)
        key = profile["customer_identity_key"]
        current = self.profiles.get(key)
        if current is None or rank > current[0]:
            self.profiles[key] = (rank, profile)


class SyncBusinessDataUseCase:
    """Idempotently synchronize five source snapshots into the sales tables.

    Snapshots (canonical English column names; the Excel/Vietnamese header
    mapping lives at the read boundary in ``etl_business.snapshot_columns``):

    - invoices (``customer_df``): one row per invoice -> ``sales_invoices``
      and the customer master (invoices are the authority for a customer's
      name/address; debt and return rows only fill customers they do not know)
    - goods (``goods_df``): invoice lines -> ``sales_invoice_lines``
    - debt (``debt_df``, optional): signed ledger -> ``customer_debt_transactions``
    - returns (``returns_df`` + ``return_lines_df``, optional): ``sales_returns``
      and ``sales_return_lines``

    ``sync_all`` validates every DataFrame before writing, then runs all
    writes in one transaction (when a unit of work is provided): it either
    commits completely or leaves the database untouched. Each snapshot is
    authoritative, so records missing from it are soft-deleted; to avoid a
    truncated or empty export wiping the data, a snapshot that is empty or
    shrinks by more than ``max_shrink_ratio`` versus the active records is
    refused unless ``allow_shrink=True``.
    """

    INVOICE_COLUMNS = {
        "issued_at",
        "invoice_number",
        "customer_name",
        "invoice_total_amount",
        "debt_delta_amount",
    }
    LINE_COLUMNS = {
        "invoice_number",
        "product_name",
        "product_category_name",
        "unit_name",
        "unit_price",
        "quantity",
        "line_amount",
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
    RETURN_OPTIONAL_COLUMNS = ("address_detail", "village_name", "ward_name")
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
        unit_of_work: IUnitOfWork | None = None,
        max_shrink_ratio: Decimal = DEFAULT_MAX_SNAPSHOT_SHRINK_RATIO,
        debt_revision_repository: IDebtRevisionRepository | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._customer_repository = customer_repository
        self._sales_invoice_repository = sales_invoice_repository
        self._sales_invoice_line_repository = sales_invoice_line_repository
        self._customer_debt_transaction_repository = customer_debt_transaction_repository
        self._sales_return_repository = sales_return_repository
        self._unit_of_work = unit_of_work or NullUnitOfWork()
        self._max_shrink_ratio = max_shrink_ratio
        self._debt_revision_repository = debt_revision_repository
        self._clock = clock

    async def sync_all(
        self,
        customer_df: pd.DataFrame,
        goods_df: pd.DataFrame,
        debt_df: pd.DataFrame | None = None,
        returns_df: pd.DataFrame | None = None,
        return_lines_df: pd.DataFrame | None = None,
        *,
        allow_shrink: bool = False,
        entrypoint: str = "unknown",
    ) -> Dict[str, Any]:
        """Validate every snapshot, then write them all in one transaction.

        ``entrypoint`` names the caller in the ``etl_sync_runs`` audit row (written
        when a debt revision repository is configured).
        """
        started_at = self._clock()
        if debt_df is not None and self._customer_debt_transaction_repository is None:
            raise DebtRepositoryRequiredError()
        if returns_df is not None:
            if self._sales_return_repository is None:
                raise SalesReturnRepositoryRequiredError()
            if return_lines_df is None:
                raise SalesReturnLinesRequiredError()

        prepared = self._prepare(customer_df, goods_df, debt_df, returns_df, return_lines_df)

        async with self._unit_of_work.transaction():
            await self._guard_snapshots(prepared, allow_shrink)

            customer_ids = await self._customer_repository.upsert_many(
                [profile for _, profile in prepared.profiles.values()]
            )
            invoice_rows = []
            for row in prepared.invoice_rows:
                identity_key = row["customer_identity_key"]
                customer_id = customer_ids.get(identity_key)
                if customer_id is None:
                    raise CustomerIdentityMissingError(identity_key=identity_key)
                invoice_rows.append(
                    {
                        **{k: v for k, v in row.items() if k != "customer_identity_key"},
                        "customer_id": customer_id,
                    }
                )
            invoice_ids = await self._sales_invoice_repository.upsert_many(invoice_rows)
            if len(invoice_ids) != len(invoice_rows):
                raise IncompleteInvoiceUpsertError()

            line_result = await self._write_lines(prepared.line_rows, invoice_ids)
            invoices_deleted = await self._sales_invoice_repository.soft_delete_missing(
                list(invoice_ids)
            )
            result: Dict[str, Any] = {
                "customers": prepared.invoice_customer_count,
                "invoices": len(invoice_rows),
                "invoices_deleted": invoices_deleted,
                "lines": line_result["lines"],
                "line_invoices": line_result["invoices"],
            }
            debt_diff: DebtSnapshotDiff | None = None
            if prepared.debt_rows is not None:
                debt_diff = await self._write_debt(prepared.debt_rows, customer_ids)
                result["debt_transactions"] = {
                    "synced": len(prepared.debt_rows),
                    "deleted": len(debt_diff.deletes),
                    "inserted": len(debt_diff.inserts),
                    "updated": len(debt_diff.updates),
                    "restored": len(debt_diff.restores),
                    "unchanged": debt_diff.unchanged,
                    "backdated": debt_diff.backdated_count,
                }
            if prepared.return_rows is not None:
                result["sales_returns"] = await self._write_returns(
                    prepared.return_rows, prepared.return_line_rows or [], customer_ids
                )
            if prepared.debt_rows is not None or prepared.return_rows is not None:
                result["customers_deleted"] = (
                    await self._customer_repository.soft_delete_unreferenced()
                )
            if self._debt_revision_repository is not None:
                result["sync_run"] = await self._record_run(
                    debt_diff, started_at, entrypoint, allow_shrink
                )
        return result

    # ------------------------------------------------------------------
    # Validation / preparation (pure; no repository access)
    # ------------------------------------------------------------------

    def _prepare(
        self,
        customer_df: pd.DataFrame,
        goods_df: pd.DataFrame,
        debt_df: pd.DataFrame | None,
        returns_df: pd.DataFrame | None,
        return_lines_df: pd.DataFrame | None,
    ) -> _PreparedSnapshots:
        prepared = _PreparedSnapshots()
        self._prepare_invoices(customer_df, prepared)
        invoice_numbers = {row["invoice_number"] for row in prepared.invoice_rows}
        prepared.line_rows = self._prepare_lines(goods_df, invoice_numbers)
        if debt_df is not None:
            prepared.debt_rows = self._prepare_debt(debt_df, prepared)
        if returns_df is not None:
            prepared.return_rows, prepared.return_line_rows = self._prepare_returns(
                returns_df, return_lines_df, prepared
            )
        return prepared

    def _prepare_invoices(self, df: pd.DataFrame, prepared: _PreparedSnapshots) -> None:
        self._require_columns(df, self.INVOICE_COLUMNS, "invoices")

        duplicated = df["invoice_number"].astype(str).str.strip().duplicated(keep=False)
        if duplicated.any():
            examples = (
                df.loc[duplicated, "invoice_number"]
                .astype(str)
                .str.strip()
                .drop_duplicates()
                .head(5)
                .tolist()
            )
            raise DuplicateInvoiceNumbersError(invoice_numbers=', '.join(examples))

        invoice_identity_keys: set[str] = set()
        for _, row in df.iterrows():
            invoice_number = self._required_text(row["invoice_number"], "invoice_number")
            customer_name = self._required_text(row["customer_name"], "customer_name")
            raw_issued_at = row["issued_at"]
            if raw_issued_at is None or pd.isna(raw_issued_at):
                raise InvoiceIssueDateRequiredError(invoice_number=invoice_number)
            timestamp = self._timestamp(raw_issued_at, "issued_at")

            address_detail = self._optional_text(row.get("address_detail"))
            village_name = self._optional_text(row.get("village_name"))
            ward_name = self._optional_text(row.get("ward_name"))
            identity_key = self.build_customer_identity_key(
                customer_name, ward_name, village_name
            )
            invoice_identity_keys.add(identity_key)
            prepared.remember_profile(
                {
                    "customer_identity_key": identity_key,
                    "customer_name": customer_name,
                    "address_detail": address_detail,
                    "village_name": village_name,
                    "ward_name": ward_name,
                },
                timestamp,
                authoritative=True,
            )
            prepared.invoice_rows.append(
                {
                    "invoice_number": invoice_number,
                    "issued_at": timestamp.to_pydatetime(),
                    "customer_identity_key": identity_key,
                    "customer_name_snapshot": customer_name,
                    "customer_address_detail_snapshot": address_detail,
                    "customer_village_name_snapshot": village_name,
                    "customer_ward_name_snapshot": ward_name,
                    "invoice_total_amount": self._decimal(
                        row["invoice_total_amount"], "invoice_total_amount"
                    ),
                    "debt_delta_amount": self._optional_decimal(
                        row.get("debt_delta_amount"), "debt_delta_amount"
                    ),
                }
            )
        prepared.invoice_customer_count = len(invoice_identity_keys)

    def _prepare_lines(
        self, df: pd.DataFrame, invoice_numbers: set[str]
    ) -> list[Dict[str, Any]]:
        self._require_columns(df, self.LINE_COLUMNS, "goods")
        referenced = self._invoice_numbers(df)
        missing = sorted(set(referenced) - invoice_numbers)
        if missing:
            raise UnknownInvoiceReferencesError(invoice_numbers=', '.join(missing[:10]))

        line_counters: Dict[str, int] = {}
        line_rows: list[Dict[str, Any]] = []
        for _, row in df.iterrows():
            invoice_number = self._required_text(row["invoice_number"], "invoice_number")
            line_number = line_counters.get(invoice_number, 0) + 1
            line_counters[invoice_number] = line_number
            line_rows.append(
                {
                    "invoice_number": invoice_number,
                    "line_number": line_number,
                    "product_name": self._required_text(row["product_name"], "product_name"),
                    "product_category_name": self._optional_text(
                        row.get("product_category_name")
                    ),
                    "unit_name": self._required_text(row["unit_name"], "unit_name"),
                    "unit_price": self._decimal(row["unit_price"], "unit_price"),
                    "quantity": self._decimal(row["quantity"], "quantity", QUANTITY_SCALE),
                    "line_amount": self._decimal(row["line_amount"], "line_amount"),
                }
            )
        return line_rows

    def _prepare_debt(
        self, df: pd.DataFrame, prepared: _PreparedSnapshots
    ) -> list[Dict[str, Any]]:
        self._require_columns(df, self.DEBT_COLUMNS, "debt transactions")
        rows: list[Dict[str, Any]] = []
        keys: set[tuple[str, str]] = set()
        for _, row in df.iterrows():
            customer_name = self._required_text(row["customer_name"], "customer_name")
            source_type = self._required_text(row["source_type"], "source_type")
            if source_type not in DEBT_SOURCE_TYPES:
                raise InvalidDebtSourceTypeError(source_type=source_type)
            source_id = self._required_text(row["source_id"], "source_id")
            if (source_type, source_id) in keys:
                raise DuplicateDebtTransactionsError()
            keys.add((source_type, source_id))

            village_name = self._optional_text(row.get("village_name"))
            ward_name = self._optional_text(row.get("ward_name"))
            identity_key = self.build_customer_identity_key(
                customer_name, ward_name, village_name
            )
            occurred_at = self._timestamp(row["occurred_at"], "occurred_at")
            prepared.remember_profile(
                {
                    "customer_identity_key": identity_key,
                    "customer_name": customer_name,
                    "address_detail": self._optional_text(row.get("address_detail")),
                    "village_name": village_name,
                    "ward_name": ward_name,
                },
                occurred_at,
                authoritative=False,
            )
            rows.append(
                {
                    "customer_identity_key": identity_key,
                    "source_type": source_type,
                    "source_id": source_id,
                    "occurred_at": occurred_at.to_pydatetime(),
                    "amount": self._decimal(row["amount"], "amount"),
                }
            )
        return rows

    def _prepare_returns(
        self,
        headers_df: pd.DataFrame,
        lines_df: pd.DataFrame | None,
        prepared: _PreparedSnapshots,
    ) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
        if lines_df is None:
            raise SalesReturnLinesRequiredError()
        self._require_columns(headers_df, self.RETURN_COLUMNS, "sales returns")
        self._require_columns(lines_df, self.RETURN_LINE_COLUMNS, "sales return lines")
        header_columns = [
            "source_id", "return_number", "occurred_at", "return_total_amount",
            "customer_name", *self.RETURN_OPTIONAL_COLUMNS,
        ]
        headers = headers_df.reindex(columns=header_columns).drop_duplicates().copy()
        if headers["source_id"].astype(str).duplicated().any():
            raise InconsistentSalesReturnHeadersError()
        if lines_df[["source_id", "source_line_id"]].astype(str).duplicated().any():
            raise DuplicateSalesReturnLinesError()
        duplicated_numbers = headers["return_number"].astype(str).str.strip().duplicated(keep=False)
        if duplicated_numbers.any():
            examples = (
                headers.loc[duplicated_numbers, "return_number"]
                .astype(str).str.strip().drop_duplicates().head(5).tolist()
            )
            raise DuplicateSalesReturnNumbersError(return_numbers=', '.join(examples))

        header_rows: list[Dict[str, Any]] = []
        for _, row in headers.iterrows():
            customer_name = self._required_text(row["customer_name"], "customer_name")
            address_detail = self._optional_text(row["address_detail"])
            village_name = self._optional_text(row["village_name"])
            ward_name = self._optional_text(row["ward_name"])
            identity_key = self.build_customer_identity_key(customer_name, ward_name, village_name)
            returned_at = self._timestamp(row["occurred_at"], "occurred_at")
            prepared.remember_profile(
                {
                    "customer_identity_key": identity_key,
                    "customer_name": customer_name,
                    "address_detail": address_detail,
                    "village_name": village_name,
                    "ward_name": ward_name,
                },
                returned_at,
                authoritative=False,
            )
            header_rows.append(
                {
                    "source_id": self._required_text(row["source_id"], "source_id"),
                    "return_number": self._required_text(row["return_number"], "return_number"),
                    "returned_at": returned_at.to_pydatetime(),
                    "customer_identity_key": identity_key,
                    "customer_name_snapshot": customer_name,
                    "customer_address_detail_snapshot": address_detail,
                    "customer_village_name_snapshot": village_name,
                    "customer_ward_name_snapshot": ward_name,
                    "return_total_amount": self._decimal(
                        row["return_total_amount"], "return_total_amount"
                    ),
                }
            )

        header_source_ids = {row["source_id"] for row in header_rows}
        line_source_ids = {str(value).strip() for value in lines_df["source_id"]}
        missing_headers = sorted(line_source_ids - header_source_ids)
        if missing_headers:
            raise UnknownSalesReturnHeadersError(header_ids=', '.join(missing_headers[:10]))

        counters: Dict[str, int] = {}
        line_rows: list[Dict[str, Any]] = []
        for _, row in lines_df.iterrows():
            source_id = self._required_text(row["source_id"], "source_id")
            counters[source_id] = counters.get(source_id, 0) + 1
            line_rows.append(
                {
                    "source_id": source_id,
                    "source_line_id": self._required_text(row["source_line_id"], "source_line_id"),
                    "line_number": counters[source_id],
                    "product_name": self._required_text(row["product_name"], "product_name"),
                    "product_category_name": self._optional_text(row.get("product_category_name")),
                    "unit_name": self._required_text(row["unit_name"], "unit_name"),
                    "unit_price": self._decimal(row["unit_price"], "unit_price"),
                    "quantity": self._decimal(row["quantity"], "quantity", QUANTITY_SCALE),
                    "line_amount": self._decimal(row["line_amount"], "line_amount"),
                }
            )
        return header_rows, line_rows

    # ------------------------------------------------------------------
    # Guards and writes
    # ------------------------------------------------------------------

    async def _guard_snapshots(
        self, prepared: _PreparedSnapshots, allow_shrink: bool
    ) -> None:
        if allow_shrink:
            return
        await self._guard_snapshot(
            "invoices", self._sales_invoice_repository, len(prepared.invoice_rows)
        )
        if prepared.debt_rows is not None:
            await self._guard_snapshot(
                "debt transactions",
                self._customer_debt_transaction_repository,
                len(prepared.debt_rows),
            )
        if prepared.return_rows is not None:
            await self._guard_snapshot(
                "sales returns", self._sales_return_repository, len(prepared.return_rows)
            )

    async def _guard_snapshot(self, name: str, repository: Any, snapshot_count: int) -> None:
        active_count = await repository.count_active()
        if active_count == 0:
            return
        if snapshot_count == 0:
            raise EmptySnapshotError(snapshot_name=name, active_count=active_count)
        shrink = Decimal(active_count - snapshot_count) / Decimal(active_count)
        if shrink > self._max_shrink_ratio:
            raise SnapshotShrinkError(
                snapshot_name=name,
                snapshot_count=snapshot_count,
                active_count=active_count,
                threshold_percent=int(self._max_shrink_ratio * 100),
            )

    async def _write_lines(
        self, line_rows: list[Dict[str, Any]], invoice_ids: Dict[str, str]
    ) -> Dict[str, int]:
        rows = [
            {
                **{k: v for k, v in row.items() if k != "invoice_number"},
                "invoice_id": invoice_ids[row["invoice_number"]],
            }
            for row in line_rows
        ]
        target_invoice_ids = list(
            dict.fromkeys(invoice_ids[row["invoice_number"]] for row in line_rows)
        )
        synced = await self._sales_invoice_line_repository.upsert_snapshot(
            rows, target_invoice_ids
        )
        return {"lines": synced, "invoices": len(target_invoice_ids)}

    async def _write_debt(
        self, debt_rows: list[Dict[str, Any]], customer_ids: Dict[str, str]
    ) -> DebtSnapshotDiff:
        incoming = []
        for row in debt_rows:
            identity_key = row["customer_identity_key"]
            customer_id = customer_ids.get(identity_key)
            if customer_id is None:
                raise CustomerIdentityMissingError(identity_key=identity_key)
            incoming.append(
                IncomingDebtRow(
                    source_type=row["source_type"],
                    source_id=row["source_id"],
                    customer_id=customer_id,
                    occurred_at=row["occurred_at"],
                    amount=row["amount"],
                )
            )
        repository = self._customer_debt_transaction_repository
        diff = diff_debt_snapshot(await repository.load_ledger_state(), incoming)
        await repository.apply_diff(diff)
        return diff

    async def _record_run(
        self,
        diff: DebtSnapshotDiff | None,
        started_at: datetime,
        entrypoint: str,
        allow_shrink: bool,
    ) -> Dict[str, Any]:
        run = EtlSyncRun(
            run_id=str(uuid4()),
            started_at=started_at,
            finished_at=self._clock(),
            entrypoint=entrypoint,
            allow_shrink=allow_shrink,
            debt_synced=diff is not None,
            is_baseline=diff is not None and diff.is_baseline,
            ledger_frontier_date=diff.frontier_date if diff else None,
            debt_inserted=len(diff.inserts) if diff else 0,
            debt_updated=len(diff.updates) if diff else 0,
            debt_deleted=len(diff.deletes) if diff else 0,
            debt_restored=len(diff.restores) if diff else 0,
            debt_backdated=diff.backdated_count if diff else 0,
        )
        changes = diff.changes if diff else ()
        revisions = diff.revisions if diff else ()
        await self._debt_revision_repository.record_run(run, changes, revisions)
        return {
            "run_id": run.run_id,
            "is_baseline": run.is_baseline,
            "retroactive_customers": len(revisions),
            "retroactive_changes": len(changes),
            # str keeps the CLI's JSON output exact (no float).
            "retroactive_delta": str(diff.retroactive_delta if diff else Decimal("0")),
        }

    async def _write_returns(
        self,
        return_rows: list[Dict[str, Any]],
        return_line_rows: list[Dict[str, Any]],
        customer_ids: Dict[str, str],
    ) -> Dict[str, int]:
        headers = []
        for row in return_rows:
            identity_key = row["customer_identity_key"]
            customer_id = customer_ids.get(identity_key)
            if customer_id is None:
                raise CustomerIdentityMissingError(identity_key=identity_key)
            headers.append(
                {
                    **{k: v for k, v in row.items() if k != "customer_identity_key"},
                    "customer_id": customer_id,
                }
            )
        return await self._sales_return_repository.sync_snapshot(headers, return_line_rows)

    # ------------------------------------------------------------------
    # Value helpers
    # ------------------------------------------------------------------

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
            raise RequiredColumnValueError(column=column)
        return text

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None or pd.isna(value):
            return None
        text = re.sub(r"\s+", " ", str(value).strip())
        return text or None

    @staticmethod
    def _timestamp(value: Any, column: str) -> pd.Timestamp:
        if value is None or pd.isna(value):
            raise RequiredColumnValueError(column=column)
        try:
            timestamp = pd.Timestamp(pd.to_datetime(value, errors="raise"))
        except (ValueError, TypeError, OverflowError) as exc:
            raise InvalidDatetimeValueError(column=column, value=str(value)) from exc
        if pd.isna(timestamp) or timestamp.tzinfo is not None:
            # Source times are naive Vietnam local time; mixing aware values
            # would make ordering/storage ambiguous.
            raise InvalidDatetimeValueError(column=column, value=str(value))
        return timestamp

    @staticmethod
    def _decimal(value: Any, column: str, scale: int = MONEY_SCALE) -> Decimal:
        """Convert to an exact Decimal rounded (half up) to the column scale.

        Rejects NaN/inf and values that would overflow NUMERIC(18, scale).
        """
        if value is None or pd.isna(value):
            raise RequiredColumnValueError(column=column)
        try:
            number = value if isinstance(value, Decimal) else Decimal(str(value))
            if not number.is_finite():
                raise InvalidOperation
            quantized = number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError) as exc:
            raise InvalidDecimalValueError(column=column, value=str(value)) from exc
        if abs(quantized) >= Decimal(10) ** (NUMERIC_PRECISION - scale):
            raise InvalidDecimalValueError(column=column, value=str(value))
        return quantized

    @staticmethod
    def _optional_decimal(
        value: Any, column: str, scale: int = MONEY_SCALE
    ) -> Decimal | None:
        if value is None or pd.isna(value):
            return None
        return SyncBusinessDataUseCase._decimal(value, column, scale)

    @staticmethod
    def _invoice_numbers(df: pd.DataFrame) -> list[str]:
        return list(
            dict.fromkeys(
                SyncBusinessDataUseCase._required_text(value, "invoice_number")
                for value in df["invoice_number"]
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
            raise MissingSnapshotColumnsError(snapshot_name=snapshot_name, columns=', '.join(missing))
