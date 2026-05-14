from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form
from dependency_injector.wiring import inject, Provide
from typing import Dict, Any, List
import io
import pandas as pd

from config.container import Container
from src.application.use_cases.ingest_data_use_case import IngestDataUseCase
from src.domain.value_objects.query_intent import QueryIntent

router = APIRouter()


@router.post("/data/ingest")
@inject
async def ingest_business_data(
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    ingest_use_case: IngestDataUseCase = Depends(Provide[Container.ingest_data_use_case])
) -> Dict[str, Any]:
    """Ingest business data from an uploaded Excel or CSV file"""
    try:
        contents = await file.read()
        filename = file.filename or ""

        if filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(contents))
        elif filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type. Use .xlsx, .xls, or .csv")

        result = await ingest_use_case.execute(df, doc_type)
        return {"message": "Data ingested successfully", "success": True, "report": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Data ingestion error: {str(e)}")


@router.get("/data/documents")
@inject
async def get_page_documents(
    doc_type : str           = Query(...),
    cursor   : str | None    = Query(None),
    page_size: int           = Query(10),
    repository: IngestDataUseCase = Depends(Provide[Container.ingest_data_use_case])
) -> Dict[str, Any]:
    """Retrieve documents with cursor-based pagination. Pass next_cursor as cursor for subsequent pages."""
    try:
        if doc_type not in [QueryIntent.TRANSACTION.value, QueryIntent.CUSTOMER.value, QueryIntent.PERIOD_SUMMARY.value, QueryIntent.ALL.value]:
            raise HTTPException(status_code=400, detail=f"Invalid doc_type '{doc_type}'. Valid types: ['transaction', 'customer', 'period_summary', 'all']")

        ids, next_cursor = await repository.repo.page_existing_ids(doc_type, cursor, page_size)
        return {
            "success"     : True,
            "doc_type"    : doc_type,
            "existing_ids": list(ids),
            "next_cursor" : next_cursor,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving documents: {str(e)}")    


@router.post("/data/batch")
@inject
async def batch_ingest_data(
    data_list: List[Dict[str, Any]],
    ingest_use_case: IngestDataUseCase = Depends(Provide[Container.ingest_data_use_case])
) -> Dict[str, Any]:
    """Batch ingest multiple business data records"""
    try:
        results = []
        for data in data_list:
            result = await ingest_use_case.execute(data)
            results.append(result)

        successful = sum(1 for r in results if r.get('success', False))

        return {
            'message': 'Batch ingestion completed',
            'total_processed': len(data_list),
            'successful': successful,
            'failed': len(data_list) - successful,
            'results': results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch ingestion error: {str(e)}")