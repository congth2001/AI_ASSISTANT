from datetime import datetime, timezone

from sqlalchemy import func, insert, select, update

from src.modules.sales.domain.models.debt_ledger import DebtLedgerRow, DebtSnapshotDiff
from src.modules.sales.domain.repositories.i_customer_debt_transaction_repository import (
    ICustomerDebtTransactionRepository,
)
from src.modules.sales.infrastructure.models import CustomerDebtTransaction
from src.modules.sales.infrastructure.repositories.repository_utils import chunked, to_decimal
from src.modules.sales.infrastructure.unit_of_work import repository_session


def _values(row: DebtLedgerRow, now: datetime) -> dict:
    return {
        "debt_transaction_id": row.debt_transaction_id,
        "customer_id": row.customer_id,
        "occurred_at": row.occurred_at,
        "amount": row.amount,
        "updated_at": now,
        "deleted_at": None,
    }


class CustomerDebtTransactionRepository(ICustomerDebtTransactionRepository):
    """Signed receivable ledger.

    The whole ledger state is loaded into memory to diff it against the snapshot;
    only a few small columns are read, which stays cheap up to roughly a million
    rows. Beyond that, diff in batches against a temporary table instead.
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def load_ledger_state(self) -> list[DebtLedgerRow]:
        statement = select(
            CustomerDebtTransaction.debt_transaction_id,
            CustomerDebtTransaction.source_type,
            CustomerDebtTransaction.source_id,
            CustomerDebtTransaction.customer_id,
            CustomerDebtTransaction.occurred_at,
            CustomerDebtTransaction.amount,
            CustomerDebtTransaction.deleted_at,
        )
        async with repository_session(self.session_factory) as session:
            rows = (await session.execute(statement)).all()
        return [
            DebtLedgerRow(
                debt_transaction_id=row.debt_transaction_id,
                source_type=row.source_type,
                source_id=row.source_id,
                customer_id=str(row.customer_id),
                occurred_at=row.occurred_at,
                amount=to_decimal(row.amount),
                deleted=row.deleted_at is not None,
            )
            for row in rows
        ]

    async def apply_diff(self, diff: DebtSnapshotDiff) -> None:
        now = datetime.now(timezone.utc)
        async with repository_session(self.session_factory) as session:
            for batch in chunked(list(diff.deletes)):
                await session.execute(
                    update(CustomerDebtTransaction)
                    .where(CustomerDebtTransaction.debt_transaction_id.in_(batch))
                    .values(deleted_at=func.now(), updated_at=func.now())
                )
            # ORM bulk UPDATE by primary key: one parameter set per changed row.
            changed = [_values(row, now) for row in (*diff.updates, *diff.restores)]
            for batch in chunked(changed):
                await session.execute(update(CustomerDebtTransaction), list(batch))
            for batch in chunked(list(diff.inserts)):
                await session.execute(
                    insert(CustomerDebtTransaction),
                    [
                        {
                            "debt_transaction_id": row.debt_transaction_id,
                            "customer_id": row.customer_id,
                            "source_type": row.source_type,
                            "source_id": row.source_id,
                            "occurred_at": row.occurred_at,
                            "amount": row.amount,
                        }
                        for row in batch
                    ],
                )

    async def count_active(self) -> int:
        async with repository_session(self.session_factory) as session:
            return int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(CustomerDebtTransaction)
                        .where(CustomerDebtTransaction.deleted_at.is_(None))
                    )
                ).scalar_one()
            )
