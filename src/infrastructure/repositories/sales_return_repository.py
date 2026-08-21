from typing import Any, Dict, List
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.domain.repositories.i_sales_return_repository import ISalesReturnRepository
from src.infrastructure.repositories.models import SalesReturn, SalesReturnLine
from src.infrastructure.repositories.repository_utils import chunked, to_decimal


class SalesReturnRepository(ISalesReturnRepository):
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def sync_snapshot(
        self,
        returns: List[Dict[str, Any]],
        lines: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        source_ids = [row["source_id"] for row in returns]
        async with self.session_factory() as session:
            stale_predicates = [SalesReturn.deleted_at.is_(None)]
            if source_ids:
                stale_predicates.append(SalesReturn.source_id.not_in(source_ids))
            await session.execute(
                update(SalesReturn)
                .where(*stale_predicates)
                .values(deleted_at=func.now())
            )

            return_ids: Dict[str, str] = {}
            for batch in chunked(returns):
                values = [
                    {
                        **row,
                        "return_id": row.get("return_id") or str(uuid4()),
                        "return_total_amount": to_decimal(row["return_total_amount"]),
                    }
                    for row in batch
                ]
                insert_stmt = pg_insert(SalesReturn).values(values)
                statement = insert_stmt.on_conflict_do_update(
                    index_elements=[SalesReturn.source_id],
                    set_={
                        "return_number": insert_stmt.excluded.return_number,
                        "returned_at": insert_stmt.excluded.returned_at,
                        "customer_id": insert_stmt.excluded.customer_id,
                        "customer_name_snapshot": insert_stmt.excluded.customer_name_snapshot,
                        "customer_address_detail_snapshot": insert_stmt.excluded.customer_address_detail_snapshot,
                        "customer_village_name_snapshot": insert_stmt.excluded.customer_village_name_snapshot,
                        "customer_ward_name_snapshot": insert_stmt.excluded.customer_ward_name_snapshot,
                        "return_total_amount": insert_stmt.excluded.return_total_amount,
                        "updated_at": func.now(),
                        "deleted_at": None,
                    },
                ).returning(SalesReturn.source_id, SalesReturn.return_id)
                return_ids.update(dict((await session.execute(statement)).all()))

            target_return_ids = list(return_ids.values())
            if target_return_ids:
                await session.execute(
                    update(SalesReturnLine)
                    .where(
                        SalesReturnLine.return_id.in_(target_return_ids),
                        SalesReturnLine.deleted_at.is_(None),
                    )
                    .values(deleted_at=func.now())
                )

            prepared_lines = []
            for item in lines:
                row = dict(item)
                source_id = row.pop("source_id")
                prepared_lines.append(
                    {
                        **row,
                        "return_id": return_ids[source_id],
                        "return_line_id": row.get("return_line_id") or str(uuid4()),
                        "unit_price": to_decimal(row["unit_price"]),
                        "quantity": to_decimal(row["quantity"]),
                        "line_amount": to_decimal(row["line_amount"]),
                    }
                )
            for batch in chunked(prepared_lines):
                insert_stmt = pg_insert(SalesReturnLine).values(batch)
                statement = insert_stmt.on_conflict_do_update(
                    constraint="uq_sales_return_lines_source",
                    set_={
                        "line_number": insert_stmt.excluded.line_number,
                        "product_name": insert_stmt.excluded.product_name,
                        "product_category_name": insert_stmt.excluded.product_category_name,
                        "unit_name": insert_stmt.excluded.unit_name,
                        "unit_price": insert_stmt.excluded.unit_price,
                        "quantity": insert_stmt.excluded.quantity,
                        "line_amount": insert_stmt.excluded.line_amount,
                        "updated_at": func.now(),
                        "deleted_at": None,
                    },
                )
                await session.execute(statement)

            await session.commit()
        return {"returns": len(returns), "lines": len(lines)}
