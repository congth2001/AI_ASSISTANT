import uuid

import pandas as pd
from src.domain.entities.document_chunk import DocumentChunk
from src.domain.value_objects.doc_type import DocType
from src.domain.interfaces.i_document_serializer import IDocumentSerializer
from src.domain.interfaces.i_ingestion_repository import IIngestionRepository

class IngestDataUseCase:
    """Use case for ingesting data into the system"""

    def __init__(
        self,
        transaction_serializer   : IDocumentSerializer,
        customer_serializer      : IDocumentSerializer,
        period_serializer        : IDocumentSerializer,
        repository               : IIngestionRepository,
    ):
        self.serializers = {
            DocType.TRANSACTION.value    : transaction_serializer,
            DocType.CUSTOMER.value       : customer_serializer,
            DocType.PERIOD_SUMMARY.value : period_serializer,
        }
        self.repo = repository

    async def execute(self, df: pd.DataFrame, doc_type: str) -> dict:
        valid_types = list(self.serializers.keys()) + [DocType.ALL.value]
        if doc_type not in valid_types:
            raise ValueError(f"Unknown doc_type '{doc_type}'. Valid types: {valid_types}")

        if doc_type == DocType.ALL.value:
            combined = {"added": 0, "skipped": 0, "updated": 0}
            for t in self.serializers:
                result = await self.execute(df.copy(), t)
                for k in combined:
                    combined[k] += result[k]
            return combined

        report = {"added": 0, "skipped": 0, "updated": 0}
        existing_ids = await self._load_all_existing_ids(doc_type)
        items = await self._prepare_chunks(doc_type, df)
        await self._upsert_chunks(doc_type, items, existing_ids, report)
        return report

    async def _load_all_existing_ids(self, doc_type: str) -> set[str]:
        page_size = 100
        existing_ids: set[str] = set()
        cursor = None
        while True:
            batch, cursor = await self.repo.page_existing_ids(doc_type, cursor, page_size=page_size)
            existing_ids.update(batch)
            if cursor is None:
                break
        return existing_ids

    async def _prepare_chunks(self, doc_type: str, df: pd.DataFrame) -> list[DocumentChunk]:
        serializer = self.serializers[doc_type]

        if doc_type == DocType.TRANSACTION.value:
            return [serializer.serialize(row) for _, row in df.iterrows()]

        if doc_type == DocType.CUSTOMER.value:
            return [serializer.serialize(df[df["Khách hàng"] == customer]) for customer in df["Khách hàng"].unique()]

        # period_summary
        df["year"] = df["Ngày"].dt.year
        df["month"] = df["Ngày"].dt.month
        items = []
        for _, row in df[["year", "month"]].drop_duplicates().iterrows():
            year, month = row["year"], row["month"]
            df_month = df[(df["year"] == year) & (df["month"] == month)]
            prev_revenue = await self.repo.get_period_revenue(year, month - 1)
            items.append(serializer.serialize(df_month, year, month, prev_revenue))
        return items

    async def _upsert_chunks(self, doc_type: str, items: list[DocumentChunk], existing_ids: set[str], report: dict) -> None:
        new_chunks = []
        for chunk in items:
            doc_id = chunk.doc_id
            if doc_id in existing_ids:
                document = await self.repo.get_by_doc_id(doc_id)
                if self._is_unchanged(doc_type, chunk, document):
                    report["skipped"] += 1
                    continue
                await self.repo.update([chunk])
                report["updated"] += 1
                continue
            new_chunks.append(chunk)
            report["added"] += 1
        await self.repo.insert(new_chunks)

    def _is_unchanged(self, doc_type: str, chunk: DocumentChunk, document: dict) -> bool:
        if chunk.metadata.get("doanh_thu", 0) != document.get("doanh_thu", 0):
            return False
        if doc_type == DocType.PERIOD_SUMMARY.value:
            return chunk.metadata.get("co_no", False) == document.get("co_no", False)
        return True
