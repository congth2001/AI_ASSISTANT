from enum import Enum

class DocType(str, Enum):
    TRANSACTION      = "transaction"
    CUSTOMER         = "customer"
    PERIOD_SUMMARY   = "period_summary"
    PRODUCT          = "product"
    ALL              = "all"
    CATEGORY         = "category"
    CATEGORY_PERIOD  = "category_period"
