from dataclasses import dataclass

@dataclass
class DocumentChunk:
    doc_id   : str
    text     : str
    metadata : dict
    doc_type : str  # "transaction" | "customer_profile" | "period_summary"