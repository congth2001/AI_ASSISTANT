from enum import Enum


class QueryStrategy(Enum):
    SIMPLE         = "simple"          # SELECT ... WHERE ... (lookup đơn)
    AGGREGATION    = "aggregation"     # GROUP BY + aggregate fn (daily/monthly/quarterly)
    TOP_N          = "top_n"           # ORDER BY metric DESC LIMIT N
    PERIOD_COMPARE = "period_compare"  # 2 sub-query so sánh kỳ này vs kỳ trước
    CTE_CHAIN      = "cte_chain"       # WITH a AS (...), b AS (...) SELECT ... (phức tạp)
    MULTI_QUERY    = "multi_query"     # nhiều query độc lập, merge ở application layer
