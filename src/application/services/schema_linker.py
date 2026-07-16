"""
Step 4: Schema Linking
Map các entity đã extract từ AnalyzedQuery → tên bảng & cột thực trong DB.
Đây là critical path — nếu bị bỏ qua, LLM sẽ sinh SQL sai schema.
"""
from dataclasses import dataclass, field
from src.domain.entities.analyzed_query import AnalyzedQuery


# ── Schema definitions ─────────────────────────────────────────────────────────

_INVOICE_CUSTOMERS_SCHEMA = """\
Table: invoice_customers
    id               TEXT     -- primary key
    invoice_id       TEXT     -- mã phiếu xuất, e.g. XB24169-0125
    date             DATETIME -- ngày giao dịch (dùng strftime('%Y/%m/%d', date) để lọc)
    name             TEXT     -- tên khách hàng đầy đủ
    address_detail   TEXT     -- chi tiết địa chỉ (số nhà, đường)
    address_village  TEXT     -- xóm/thôn
    address_ward     TEXT     -- xã/phường
    total_amount     REAL     -- tổng tiền hóa đơn (VND)
    debt_amount      REAL     -- số tiền còn nợ (NULL hoặc 0 = đã thanh toán)
    created_at       DATETIME
    deleted_at       DATETIME -- NULL nếu chưa xóa mềm; luôn thêm WHERE deleted_at IS NULL
"""

_INVOICE_GOODS_SCHEMA = """\
Table: invoice_goods
    id          TEXT   -- primary key
    invoice_id  TEXT   -- liên kết với invoice_customers.invoice_id
    name        TEXT   -- tên hàng hóa / sản phẩm
    category    TEXT   -- danh mục hàng
    unit_type   TEXT   -- đơn vị tính (kg, hộp, cái, ...)
    unit_price  REAL   -- đơn giá (VND)
    quantity    REAL   -- số lượng
    total_price REAL   -- thành tiền = unit_price × quantity
    created_at  DATETIME
    deleted_at  DATETIME -- NULL nếu chưa xóa mềm; luôn thêm WHERE deleted_at IS NULL
"""

_JOIN_HINT = (
    "JOIN: invoice_customers.invoice_id = invoice_goods.invoice_id\n"
    "DATE filter: strftime('%Y', date)='2024' / strftime('%m', date)='03' / strftime('%d', date)='15'"
)

_FULL_SCHEMA = _INVOICE_CUSTOMERS_SCHEMA + "\n" + _INVOICE_GOODS_SCHEMA + "\n" + _JOIN_HINT


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class LinkedSchema:
    """Kết quả sau bước schema linking."""
    primary_table  : str                              # bảng chính cần query
    filter_hints   : dict = field(default_factory=dict)  # entity → giá trị lọc
    schema_context : str = ""                         # full schema text đưa vào LLM prompt
    entity_summary : str = ""                         # tóm tắt entity để LLM hiểu ngữ cảnh


# ── SchemaLinker ───────────────────────────────────────────────────────────────

class SchemaLinker:
    """
    Map AnalyzedQuery → LinkedSchema.

    Không gọi LLM, chỉ ánh xạ tĩnh entity ↔ cột DB.

    Quy tắc chọn primary_table:
      - category_name có giá trị → invoice_goods (JOIN invoice_customers)
      - ngược lại → invoice_customers
    """

    def link(self, analyzed: AnalyzedQuery) -> LinkedSchema:
        hints: dict       = {}
        entity_parts: list[str] = []

        # ── Time filter → strftime trên cột date ──────────────────────────────
        tf = analyzed.time_filter
        if tf.year:
            hints["date_year"]  = tf.year
            entity_parts.append(f"năm={tf.year}")
        if tf.month:
            hints["date_month"] = tf.month
            entity_parts.append(f"tháng={tf.month}")
        if tf.quarter:
            hints["date_quarter"] = tf.quarter
            entity_parts.append(f"quý={tf.quarter}")
        if tf.day:
            hints["date_day"] = tf.day
            entity_parts.append(f"ngày={tf.day}")

        # ── Customer → invoice_customers.name ────────────────────────────────
        if analyzed.customer_name:
            hints["customer_name"] = analyzed.customer_name
            entity_parts.append(f"khách_hàng='{analyzed.customer_name}'")

        # ── Invoice → invoice_customers.invoice_id ───────────────────────────
        if analyzed.invoice_id:
            hints["invoice_id"] = analyzed.invoice_id
            entity_parts.append(f"phiếu='{analyzed.invoice_id}'")

        # ── Category → invoice_goods.category ────────────────────────────────
        if analyzed.category_name:
            hints["category"] = analyzed.category_name
            entity_parts.append(f"danh_mục='{analyzed.category_name}'")

        # ── Top-N ─────────────────────────────────────────────────────────────
        if analyzed.top_n:
            hints["top_n"] = analyzed.top_n

        # ── Primary table selection ───────────────────────────────────────────
        needs_goods = bool(analyzed.category_name)
        primary_table = "invoice_goods" if needs_goods else "invoice_customers"

        entity_summary = (
            ", ".join(entity_parts) if entity_parts else "không có bộ lọc cụ thể"
        )

        return LinkedSchema(
            primary_table  = primary_table,
            filter_hints   = hints,
            schema_context = _FULL_SCHEMA,
            entity_summary = entity_summary,
        )
