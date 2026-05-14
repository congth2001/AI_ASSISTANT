import json
import os
import uuid
import pandas as pd
from src.domain.interfaces.i_document_serializer import IDocumentSerializer
from src.domain.entities.document_chunk import DocumentChunk
from src.domain.value_objects.doc_type import DocType

class CustomerSerializer(IDocumentSerializer):
    def __init__(self): 
        pass

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
        
        customer_id = ten_kh.strip().lower().replace(" ", "_")

        metadata = {
            "doc_type"   : DocType.CUSTOMER.value,
            "customer_id": customer_id,
            "ten_kh"     : ten_kh,
            "xa"         : xa,
            "xom"        : xom,
            "so_phieu"   : so_phieu,
            "doanh_thu"  : float(tong_tien),
            "tong_no"    : float(tong_no),
            "co_no"      : tong_no > 0,
            "year_start" : int(ngay_dau.year),
            "year_end"   : int(ngay_cuoi.year),
        }

        return DocumentChunk(
            doc_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"customer_{customer_id}").hex,
            text=text,
            metadata=metadata,
            doc_type=DocType.CUSTOMER.value
        )
    
    def save_jsonl(self, chunks: list[DocumentChunk], file_path: str = "data/ingestions/customers.jsonl"):
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
