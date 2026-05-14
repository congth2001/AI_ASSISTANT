import os
import json
import uuid
import pandas as pd
from src.domain.interfaces.i_document_serializer import IDocumentSerializer
from src.domain.entities.document_chunk import DocumentChunk
from src.domain.value_objects.doc_type import DocType

class PeriodSummarySerializer(IDocumentSerializer):
    def __init__(self):
        pass

    def serialize(
        self, 
        df_month: pd.DataFrame,
        year: int,
        month: int,
        prev_month_revenue: float | None = None,
    ) -> DocumentChunk:

        so_phieu  = len(df_month)
        doanh_thu = df_month["Tổng tiền"].sum()
        ghi_no    = df_month["Ghi nợ"].sum()
        so_kh     = df_month["Khách hàng"].nunique()
        tb_phieu  = doanh_thu / so_phieu if so_phieu > 0 else 0

        # Top 3 khách hàng theo doanh thu
        top_kh = (
            df_month.groupby("Khách hàng")["Tổng tiền"]
            .sum()
            .nlargest(3)
            .index.tolist()
        )
        top_xa = (
            df_month.groupby("Xã")["Tổng tiền"]
            .sum()
            .nlargest(3)
            .index.tolist()
        )

        # Tăng trưởng
        if prev_month_revenue and prev_month_revenue > 0:
            tang_truong = (doanh_thu - prev_month_revenue) / prev_month_revenue * 100
            tang_truong_desc = f"{tang_truong:+.1f}% so với tháng trước"
        else:
            tang_truong_desc = "không có dữ liệu tháng trước để so sánh"

        ten_thang = [
            "", "Một", "Hai", "Ba", "Tư", "Năm", "Sáu",
            "Bảy", "Tám", "Chín", "Mười", "Mười một", "Mười hai"
        ][month]

        text = (
            f"Báo cáo kinh doanh tháng {ten_thang} ({month:02d}/{year}): "
            f"Tổng doanh thu {doanh_thu:,.0f} VND, {tang_truong_desc}. "
            f"Số phiếu xuất: {so_phieu} phiếu từ {so_kh} khách hàng, "
            f"giá trị trung bình mỗi phiếu {tb_phieu:,.0f} VND. "
            f"Tổng ghi nợ mới: {ghi_no:,.0f} VND. "
            f"Top khách hàng: {', '.join(top_kh)}. "
            f"Khu vực mua nhiều nhất: {', '.join(top_xa)}."
        )

        metadata = {
            "doc_type" : DocType.PERIOD_SUMMARY.value,
            "year"     : year,
            "month"    : month,
            "quarter"  : (month - 1) // 3 + 1,
            "doanh_thu": float(doanh_thu),
            "so_phieu" : so_phieu,
            "so_kh"    : so_kh,
            "co_no"    : ghi_no > 0
        }

        return DocumentChunk(
            doc_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"period_summary_{year}_{month}").hex,
            text=text,
            metadata=metadata,
            doc_type=DocType.PERIOD_SUMMARY.value
        )

    def save_jsonl(self, chunks: list[DocumentChunk], file_path: str = "data/ingestions/period_summaries.jsonl"):
        # ensure target directory exists
        dir_path = os.path.dirname(file_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            for chunk in chunks:
                json_line = {
                    "doc_id": chunk.doc_id,
                    "text": chunk.text,
                    "metadata": chunk.metadata,
                    "doc_type": chunk.doc_type
                }
                f.write(json.dumps(json_line, ensure_ascii=False) + "\n")