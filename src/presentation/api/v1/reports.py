from fastapi import APIRouter, Depends, HTTPException, Query
from dependency_injector.wiring import inject, Provide
from typing import Optional, Dict, Any, List
from datetime import date

from config.container import Container
from src.application.use_cases.query_report_use_case import QueryReportUseCase
from src.domain.entities.date_range import DateRange

router = APIRouter()


@router.get("/reports")
@inject
async def query_report(
    query: str = Query(..., description="Business query (e.g., 'What is our revenue this month?')"),
    start_date: Optional[date] = Query(None, description="Start date for data filtering"),
    end_date: Optional[date] = Query(None, description="End date for data filtering"),
    report_use_case: QueryReportUseCase = Depends(Provide[Container.query_report_use_case])
) -> Dict[str, Any]:
    """Query business reports and analytics"""
    try:
        # Build date range if provided
        date_range = None
        if start_date and end_date:
            date_range = DateRange.from_dates(start_date, end_date)
        elif start_date:
            date_range = DateRange.from_dates(start_date, date.today())
        elif end_date:
            # Default to last 30 days if only end_date provided
            start_date = end_date.replace(day=max(1, end_date.day - 30))
            date_range = DateRange.from_dates(start_date, end_date)

        result = await report_use_case.execute(query, date_range)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report query error: {str(e)}")


@router.post("/reports/custom")
@inject
async def custom_report(
    request: Dict[str, Any],
    report_use_case: QueryReportUseCase = Depends(Provide[Container.query_report_use_case])
) -> Dict[str, Any]:
    """Create custom business report"""
    try:
        query = request.get('query', '')
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        # Extract date range from request
        date_range = None
        if 'start_date' in request and 'end_date' in request:
            date_range = DateRange.from_dates(
                date.fromisoformat(request['start_date']),
                date.fromisoformat(request['end_date'])
            )

        result = await report_use_case.execute(query, date_range)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Custom report error: {str(e)}")