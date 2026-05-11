from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, List

from src.application.use_cases.ingest_data_use_case import IngestDataUseCase

router = APIRouter()


@router.post("/data/ingest")
async def ingest_business_data(
    data: Dict[str, Any],
    ingest_use_case: IngestDataUseCase = Depends()
) -> Dict[str, Any]:
    """Ingest business data into the system"""
    try:
        result = await ingest_use_case.execute(data)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Data ingestion error: {str(e)}")


@router.post("/data/batch")
async def batch_ingest_data(
    data_list: List[Dict[str, Any]],
    ingest_use_case: IngestDataUseCase = Depends()
) -> Dict[str, Any]:
    """Batch ingest multiple business data records"""
    try:
        results = []
        for data in data_list:
            result = await ingest_use_case.execute(data)
            results.append(result)

        successful = sum(1 for r in results if r.get('success', False))

        return {
            'total_processed': len(data_list),
            'successful': successful,
            'failed': len(data_list) - successful,
            'results': results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch ingestion error: {str(e)}")