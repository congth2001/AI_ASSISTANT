from typing import Optional, Dict, Any, List
from src.domain.interfaces.i_data_repository import IDataRepository
from src.domain.interfaces.i_llm_service import ILLMService
from src.domain.entities.report import Report, MetricSummary
from src.domain.value_objects.date_range import DateRange
from src.domain.value_objects.metric_type import MetricType
from decimal import Decimal
import json


class QueryReportUseCase:
    """Use case for querying business reports and analytics"""

    def __init__(
        self,
        data_repo: IDataRepository,
        llm_service: ILLMService
    ):
        self.data_repo = data_repo
        self.llm_service = llm_service

    async def execute(self, query: str, date_range: Optional[DateRange] = None) -> Dict[str, Any]:
        """Execute report query"""
        # Get relevant business data
        business_data = await self._get_relevant_data(query, date_range)

        # Generate insights using LLM
        insights = await self._generate_insights(query, business_data)

        # Create metric summaries
        summaries = self._create_metric_summaries(business_data)

        # Generate recommendations
        recommendations = await self._generate_recommendations(query, business_data, insights)

        # Create report entity
        report = Report(
            title=f"Report: {query[:50]}",
            report_type=self._classify_report_type(query),
            date_range=date_range or DateRange.last_n_days(30),
            data={
                'business_data': business_data,
                'summaries': [summary.__dict__ for summary in summaries]
            },
            insights=insights,
            recommendations=recommendations
        )

        return {
            'report': {
                'id': report.id,
                'title': report.title,
                'type': report.report_type,
                'date_range': {
                    'start': report.date_range.start_date.isoformat(),
                    'end': report.date_range.end_date.isoformat()
                },
                'insights': report.insights,
                'recommendations': report.recommendations,
                'data': report.data
            },
            'generated_at': report.generated_at.isoformat()
        }

    async def _get_relevant_data(self, query: str, date_range: Optional[DateRange]) -> List[Dict[str, Any]]:
        """Get relevant business data based on query"""
        # Extract data types from query
        data_types = self._extract_data_types(query)

        all_data = []
        for data_type in data_types:
            data = await self.data_repo.get_business_data(data_type, date_range)
            all_data.extend(data)

        return all_data

    def _extract_data_types(self, query: str) -> List[str]:
        """Extract relevant data types from query"""
        query_lower = query.lower()
        data_types = []

        type_keywords = {
            'revenue': ['revenue', 'income', 'sales', 'earnings'],
            'profit': ['profit', 'loss', 'margin', 'net profit'],
            'customer': ['customer', 'client', 'buyer', 'user'],
            'inventory': ['inventory', 'stock', 'product', 'item']
        }

        for data_type, keywords in type_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                data_types.append(data_type)

        # Default to revenue if no specific type found
        if not data_types:
            data_types = ['revenue']

        return data_types

    async def _generate_insights(self, query: str, data: List[Dict[str, Any]]) -> List[str]:
        """Generate insights using LLM"""
        if not data:
            return ["No data available for analysis"]

        # Prepare data summary for LLM
        data_summary = self._summarize_data(data)

        prompt = f"""
        Analyze the following business data and provide key insights for the query: "{query}"

        Data Summary:
        {data_summary}

        Provide 3-5 key insights about this data. Focus on trends, patterns, and notable observations.
        """

        response = await self.llm_service.generate_response(prompt)
        insights = [line.strip('- ').strip() for line in response.split('\n') if line.strip().startswith('-')]
        return insights[:5] if insights else [response]

    def _summarize_data(self, data: List[Dict[str, Any]]) -> str:
        """Create a text summary of the data"""
        if not data:
            return "No data available"

        # Group by data type
        type_groups = {}
        for item in data:
            data_type = item.get('data_type', 'unknown')
            if data_type not in type_groups:
                type_groups[data_type] = []
            type_groups[data_type].append(item)

        summary_parts = []
        for data_type, items in type_groups.items():
            total_items = len(items)
            values = [item.get('value', 0) for item in items]
            avg_value = sum(values) / len(values) if values else 0
            summary_parts.append(f"{data_type}: {total_items} records, average value: {avg_value:.2f}")

        return "; ".join(summary_parts)

    def _create_metric_summaries(self, data: List[Dict[str, Any]]) -> List[MetricSummary]:
        """Create metric summaries from data"""
        summaries = []

        # Group by data type
        type_groups = {}
        for item in data:
            data_type = item.get('data_type', 'unknown')
            if data_type not in type_groups:
                type_groups[data_type] = []
            type_groups[data_type].append(item)

        for data_type, items in type_groups.items():
            if not items:
                continue

            values = [Decimal(str(item.get('value', 0))) for item in items]
            total = sum(values)
            count = len(values)

            # Calculate simple metrics
            summary = MetricSummary(
                metric_type=data_type,
                value=total,
                period='total',
                date=items[0].get('date') if items else None
            )
            summaries.append(summary)

        return summaries

    async def _generate_recommendations(self, query: str, data: List[Dict[str, Any]], insights: List[str]) -> List[str]:
        """Generate recommendations using LLM"""
        if not data:
            return ["Collect more business data to enable analysis"]

        data_summary = self._summarize_data(data)

        prompt = f"""
        Based on the following business data and insights, provide actionable recommendations for: "{query}"

        Data Summary:
        {data_summary}

        Key Insights:
        {chr(10).join(f"- {insight}" for insight in insights)}

        Provide 2-4 specific, actionable recommendations.
        """

        response = await self.llm_service.generate_response(prompt)
        recommendations = [line.strip('- ').strip() for line in response.split('\n') if line.strip().startswith('-')]
        return recommendations[:4] if recommendations else [response]

    def _classify_report_type(self, query: str) -> str:
        """Classify the type of report being requested"""
        query_lower = query.lower()

        if any(word in query_lower for word in ['trend', 'change', 'growth', 'decline']):
            return 'trend_analysis'
        elif any(word in query_lower for word in ['compare', 'vs', 'versus', 'difference']):
            return 'comparison'
        elif any(word in query_lower for word in ['customer', 'client', 'buyer']):
            return 'customer_analysis'
        elif any(word in query_lower for word in ['revenue', 'sales', 'income']):
            return 'revenue_analysis'
        elif any(word in query_lower for word in ['profit', 'loss', 'margin']):
            return 'profit_analysis'
        else:
            return 'general_report'