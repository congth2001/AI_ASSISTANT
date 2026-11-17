from typing import Any, Dict, List
from uuid import uuid4

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.modules.sales.domain.repositories.i_customer_debt_transaction_repository import (
    ICustomerDebtTransactionRepository,
)
from src.modules.sales.infrastructure.models import CustomerDebtTransaction
from src.modules.sales.infrastructure.repositories.repository_utils import chunked, to_decimal
from src.modules.sales.infrastructure.unit_of_work import repository_session


class CustomerDebtTransactionRepository(ICustomerDebtTransactionRepository):
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def sync_snapshot(self, rows: List[Dict[str, Any]]) -> Dict[str, int]:
        source_keys = {(row["source_type"], row["source_id"]) for row in rows}
        inserted_or_updated = 0
        async with repository_session(self.session_factory) as session:
            existing = set(
                (await session.execute(select(
                    CustomerDebtTransaction.source_type,
                    CustomerDebtTransaction.source_id,
                ).where(CustomerDebtTransaction.deleted_at.is_(None)))).all()
            )
            stale = existing - source_keys
            for batch in chunked(list(stale)):
                await session.execute(
                    update(CustomerDebtTransaction)
                    .where(
                        tuple_(
                            CustomerDebtTransaction.source_type,
                            CustomerDebtTransaction.source_id,
                        ).in_(batch),
                    )
                    .values(deleted_at=func.now(), updated_at=func.now())
                )
            for batch in chunked(rows):
                values = [
                    {
                        **row,
                        "debt_transaction_id": str(uuid4()),
                        "amount": to_decimal(row["amount"]),
                    }
                    for row in batch
                ]
                insert_stmt = pg_insert(CustomerDebtTransaction).values(values)
                await session.execute(
                    insert_stmt.on_conflict_do_update(
                        constraint="uq_debt_transactions_source",
                        set_={
                            "customer_id": insert_stmt.excluded.customer_id,
                            "occurred_at": insert_stmt.excluded.occurred_at,
                            "amount": insert_stmt.excluded.amount,
                            "updated_at": func.now(),
                            "deleted_at": None,
                        },
                    )
                )
                inserted_or_updated += len(values)
        return {"synced": inserted_or_updated, "deleted": len(stale)}

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
