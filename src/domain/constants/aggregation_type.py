from enum import Enum


class AggregationType(Enum):
    NONE            = "none"
    TOP_CUSTOMERS   = "top_customers"   # top N khách hàng theo doanh thu trong kỳ
    DAILY_REVENUE   = "daily_revenue"   # group by day → tìm ngày doanh thu max/min
    WEEKLY_REVENUE  = "weekly_revenue"  # group by week → tìm tuần doanh thu max/min
    MONTHLY_REVENUE = "monthly_revenue" # group by month trong 1 năm
    QUARTERLY_REVENUE = "quarterly_revenue" # group by quarter trong 1 năm
    YEARLY_REVENUE  = "yearly_revenue"  # group by year → tìm năm doanh thu max/min

