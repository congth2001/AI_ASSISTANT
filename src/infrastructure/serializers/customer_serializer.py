import uuid

import pandas as pd
from src.domain.interfaces.i_document_serializer import IDocumentSerializer
from src.domain.entities.document_chunk import DocumentChunk

class CustomerSerializer(IDocumentSerializer):

    def serialize(self, group: pd.DataFrame) -> DocumentChunk:
        ten_kh    = group["Khách hàng"].iloc[0]
        xa        = str(group["Xã"].iloc[0]).strip()
        xom       = str(group["Xóm"].iloc[0]).strip()
        ngay_dau  = group["Ngày"].min()
        ngay_cuoi = group["Ngày"].max()

        so_phieu   = len(group)
        tong_tien  = group["Tổng tiền"].sum()
        tong_no    = group["Ghi nợ"].sum()       # âm = KH đang có số dư
        da_tra     = tong_tien - tong_no

        # Tần suất: trung bình bao nhiêu ngày giữa 2 lần mua
        if so_phieu > 1:
            span_days = (ngay_cuoi - ngay_dau).days
            tan_suat  = f"trung bình {span_days // so_phieu} ngày/lần"
        else:
            tan_suat  = "mới giao dịch 1 lần"

        # Trạng thái công nợ
        if tong_no < 0:
            no_desc = f"đang có số dư {abs(tong_no):,.0f} VND (trả dư)"
        elif tong_no == 0:
            no_desc = "không có công nợ"
        else:
            no_desc = f"còn nợ {tong_no:,.0f} VND"

        text = (
            f"Hồ sơ khách hàng {ten_kh}, địa chỉ {xom} - {xa}. "
            f"Tổng giao dịch: {so_phieu} phiếu xuất "
            f"từ {ngay_dau.strftime('%m/%Y')} đến {ngay_cuoi.strftime('%m/%Y')}, "
            f"mua hàng {tan_suat}. "
            f"Doanh thu tích lũy: {tong_tien:,.0f} VND, "
            f"đã thanh toán: {da_tra:,.0f} VND. "
            f"Công nợ: {no_desc}."
        )

        metadata = {
            "doc_type"   : "customer",
            "customer_id": ten_kh.strip().lower().replace(" ", "_"),
            "ten_kh"     : ten_kh,
            "xa"         : xa,
            "xom"        : xom,
            "so_phieu"   : so_phieu,
            "tong_tien"  : float(tong_tien),
            "tong_no"    : float(tong_no),
            "co_no"      : tong_no > 0,
            "year_start" : int(ngay_dau.year),
            "year_end"   : int(ngay_cuoi.year),
        }

        return DocumentChunk(
            doc_id=uuid.uuid1(),
            text=text,
            metadata=metadata,
            doc_type="customer"
        )
    
    def get_doc_id(self, data):
        return f"{data['metadata']['customer_id']}"