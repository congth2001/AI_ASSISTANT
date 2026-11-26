from collections.abc import Sequence

from sqlalchemy import insert

from src.modules.sales.domain.models.debt_ledger import (
    CustomerDebtRevision as CustomerDebtRevisionData,
    DebtTransactionChange,
    EtlSyncRun as EtlSyncRunData,
)
from src.modules.sales.domain.repositories.i_debt_revision_repository import (
    IDebtRevisionRepository,
)
from src.modules.sales.infrastructure.models import (
    CustomerDebtRevision,
    CustomerDebtTransactionChange,
    EtlSyncRun,
)
from src.modules.sales.infrastructure.repositories.repository_utils import chunked
from src.modules.sales.infrastructure.unit_of_work import repository_session


class DebtRevisionRepository(IDebtRevisionRepository):
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def record_run(
        self,
        run: EtlSyncRunData,
        changes: Sequence[DebtTransactionChange],
        revisions: Sequence[CustomerDebtRevisionData],
    ) -> None:
        async with repository_session(self.session_factory) as session:
            await session.execute(
                insert(EtlSyncRun).values(
                    run_id=run.run_id,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    entrypoint=run.entrypoint,
                    allow_shrink=run.allow_shrink,
                    debt_synced=run.debt_synced,
                    is_baseline=run.is_baseline,
                    ledger_frontier_date=run.ledger_frontier_date,
                    debt_inserted=run.debt_inserted,
                    debt_updated=run.debt_updated,
                    debt_deleted=run.debt_deleted,
                    debt_restored=run.debt_restored,
                    debt_backdated=run.debt_backdated,
                )
            )
            for batch in chunked(list(changes)):
                await session.execute(
                    insert(CustomerDebtTransactionChange),
                    [
                        {
                            "run_id": run.run_id,
                            "debt_transaction_id": change.debt_transaction_id,
                            "customer_id": change.customer_id,
                            "previous_customer_id": change.previous_customer_id,
                            "change_type": change.change_type.value,
                            "source_type": change.source_type,
                            "source_id": change.source_id,
                            "old_occurred_at": change.old_occurred_at,
                            "new_occurred_at": change.new_occurred_at,
                            "old_amount": change.old_amount,
                            "new_amount": change.new_amount,
                            "balance_delta": change.balance_delta,
                        }
                        for change in batch
                    ],
                )
            for batch in chunked(list(revisions)):
                await session.execute(
                    insert(CustomerDebtRevision),
                    [
                        {
                            "run_id": run.run_id,
                            "customer_id": revision.customer_id,
                            "balance_before": revision.balance_before,
                            "balance_after": revision.balance_after,
                            "balance_delta": revision.balance_delta,
                            "earliest_affected_at": revision.earliest_affected_at,
                            "change_count": revision.change_count,
                        }
                        for revision in batch
                    ],
                )
