from datetime import datetime
import uuid

from domain.interfaces.i_document_serializer import IDocumentSerializer
from domain.entities.document_chunk import DocumentChunk
import pandas as pd

class TransactionSerializer(IDocumentSerializer):
    """Serialize for transaction data from Excel to DocumentChunk format for vectorization and storage"""

    def serialize(self, row: pd.Series) -> dict:

        ngay: datetime = row["Ngày"]
        so_phieu: str  = row["Số phiếu"]
        ten_kh: str    = row["Khách hàng"]
        xa: str        = str(row["Xã"]).strip()
        xom: str       = str(row["Xóm"]).strip()
        tong_tien: float = float(row["Tổng tiền"])
        ghi_no: float    = float(row["Ghi nợ"])

        payment_desc = self.classify_payment_status(tong_tien, ghi_no)

        text = (
            f"Phiếu xuất {so_phieu} ngày {ngay.strftime('%d/%m/%Y')} "
            f"lúc {ngay.strftime('%H:%M')}: "
            f"Khách hàng {ten_kh}, địa chỉ {xom} - {xa}. "
            f"Tổng tiền: {tong_tien:,.0f} VND. "
            f"Thanh toán: {payment_desc}."
        )

        metadata = {
            "doc_type"   : "transaction",
            "so_phieu"   : so_phieu,
            # Dùng slug để tránh trùng lặp khi tên KH viết khác nhau
            "customer_id": ten_kh.strip().lower().replace(" ", "_"),
            "ten_kh"     : ten_kh,
            "xa"         : xa,
            "xom"        : xom,
            "year"       : ngay.year,
            "month"      : ngay.month,
            "day"        : ngay.day,
            "tong_tien"  : tong_tien,
            "ghi_no"     : ghi_no,
            # Filter nhanh theo trạng thái nợ
            "co_no"      : ghi_no > 0,
        }

        return DocumentChunk(
            doc_id=uuid.uuid1(),
            text=text,
            metadata=metadata,
            doc_type="transaction"
        )
    
    def get_doc_id(self, data):
        return f"{data['metadata']['so_phieu']}_{data['metadata']['customer_id']}"

    def classify_payment_status(self, tong_tien: float, ghi_no: float) -> str:
        """
            Ghi nợ < 0   → khách trả dư (hoàn tiền/thu lại)
            Ghi nợ = 0   → thanh toán ngay, không nợ
            0 < Ghi nợ < Tổng tiền → trả một phần, còn nợ lại
            Ghi nợ = Tổng tiền     → toàn bộ đơn ghi nợ
        """
        if ghi_no < 0:
            return f"khách trả dư {abs(ghi_no):,.0f} VND (hoàn/thu lại)"
        elif ghi_no == 0:
            return "thanh toán ngay, không ghi nợ"
        elif ghi_no < tong_tien:
            da_tra = tong_tien - ghi_no
            return f"trả {da_tra:,.0f} VND, còn nợ lại {ghi_no:,.0f} VND"
        else:
            return f"ghi nợ toàn bộ {ghi_no:,.0f} VND"