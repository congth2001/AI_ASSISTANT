import pandas as pd
from domain.interfaces.i_document_serializer import IDocumentSerializer
from domain.interfaces.i_ingestion_repository import IIngestionRepository

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
            "transaction"      : transaction_serializer,
            "customer_profile" : customer_serializer,
            "period_summary"   : period_serializer,
        }
        self.repo = repository

    def execute(self, df: pd.DataFrame) -> dict:
        report = {"added": 0, "skipped": 0, "upserted": 0}

        # Layer 1: transactions — append only
        existing_ids = self.repo.list_existing_ids("transaction")
        serializer = self.serializers["transaction"]
        new_chunks = []
        for _, row in df.iterrows():
            doc_id = serializer.get_doc_id(row)
            if doc_id not in existing_ids:
                new_chunks.append(serializer.serialize(row))
                report["added"] += 1
            else:
                report["skipped"] += 1
        self.repo.save(new_chunks)

        # Layer 2: customer profiles — upsert
        affected_customers = df["Khách hàng"].unique()
        serializer = self.serializers["customer_profile"]
        for customer in affected_customers:
            group = df[df["Khách hàng"] == customer]
            chunk = serializer.serialize(group)
            self.repo.upsert(chunk)
            report["upserted"] += 1

        return report