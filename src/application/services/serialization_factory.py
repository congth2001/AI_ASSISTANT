# ─────────────────────────────────────────────
# 1. HELPER: Phân loại trạng thái thanh toán
# ─────────────────────────────────────────────
import datetime

import pandas as pd

def classify_payment_status(tong_tien: float, ghi_no: float) -> str:
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


# ─────────────────────────────────────────────
# 2. LAYER 1: Transaction Document
#    1 row Khách hàng → 1 document
#    Dùng cho: tra cứu phiếu, lịch sử giao dịch cụ thể
# ─────────────────────────────────────────────

def serialize_transaction(row: pd.Series) -> dict:
    """
    Input : 1 row từ sheet Khách hàng
    Output: {"text": ..., "metadata": ...}
    """
    ngay: datetime.datetime = row["Ngày"]
    so_phieu: str  = row["Số phiếu"]
    ten_kh: str    = row["Khách hàng"]
    xa: str        = str(row["Xã"]).strip()
    xom: str       = str(row["Xóm"]).strip()
    tong_tien: float = float(row["Tổng tiền"])
    ghi_no: float    = float(row["Ghi nợ"])

    payment_desc = classify_payment_status(tong_tien, ghi_no)

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
        "doanh_thu"  : tong_tien,
        "ghi_no"     : ghi_no,
        # Filter nhanh theo trạng thái nợ
        "co_no"      : ghi_no > 0,
    }

    return {"text": text, "metadata": metadata}


# ─────────────────────────────────────────────
# 3. LAYER 2: Customer Profile Document
#    Aggregate toàn bộ lịch sử 1 khách → 1 document
#    Dùng cho: phân tích KH, tổng công nợ, VIP ranking
# ─────────────────────────────────────────────

def serialize_customer_profile(group: pd.DataFrame) -> dict:
    """
    Input : DataFrame đã groupby('Khách hàng') của 1 khách
    Output: {"text": ..., "metadata": ...}
    """
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
        "doanh_thu"  : float(tong_tien),
        "tong_no"    : float(tong_no),
        "co_no"      : bool(tong_no > 0),
        "year_start" : int(ngay_dau.year),
        "year_end"   : int(ngay_cuoi.year),
    }

    return {"text": text, "metadata": metadata}


# ─────────────────────────────────────────────
# 4. LAYER 3: Period Summary Document
#    Aggregate theo từng tháng → 1 document/tháng
#    Dùng cho: báo cáo doanh thu, so sánh kỳ, xu hướng
# ─────────────────────────────────────────────

def serialize_period_summary(
    df_month: pd.DataFrame,
    year: int,
    month: int,
    prev_month_revenue: float | None = None,
) -> dict:
    """
    Input : DataFrame đã filter theo year/month, doanh thu tháng trước
    Output: {"text": ..., "metadata": ...}
    """
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
        "doc_type" : "period_summary",
        "year"     : year,
        "month"    : month,
        "quarter"  : (month - 1) // 3 + 1,
        "doanh_thu": float(doanh_thu),
        "so_phieu" : so_phieu,
        "so_kh"    : so_kh,
    }

    return {"text": text, "metadata": metadata}


# ─────────────────────────────────────────────
# 5. PIPELINE: Chạy toàn bộ
# ─────────────────────────────────────────────
def build_all_documents(filepath: str) -> list[dict]:
    """
    Đọc file Excel, tạo toàn bộ documents cho 3 layer.
    """
    df = pd.read_excel(filepath, sheet_name="Khách hàng")
    df["Ngày"] = pd.to_datetime(df["Ngày"])
    df["Tổng tiền"] = pd.to_numeric(df["Tổng tiền"], errors="coerce").fillna(0)
    df["Ghi nợ"]    = pd.to_numeric(df["Ghi nợ"],    errors="coerce").fillna(0)

    documents = []

    # Layer 1 — Transaction (1 row = 1 doc)
    for _, row in df.iterrows():
        documents.append(serialize_transaction(row))

    # Layer 2 — Customer Profile (group by tên KH)
    for ten_kh, group in df.groupby("Khách hàng"):
        documents.append(serialize_customer_profile(group))

    # Layer 3 — Period Summary (group by year + month)
    df["_ym"] = df["Ngày"].dt.to_period("M")
    periods   = sorted(df["_ym"].unique())
    rev_map   = {
        p: df[df["_ym"] == p]["Tổng tiền"].sum()
        for p in periods
    }

    for i, period in enumerate(periods):
        df_month = df[df["_ym"] == period]
        prev_rev = rev_map[periods[i - 1]] if i > 0 else None
        documents.append(
            serialize_period_summary(
                df_month,
                year=period.year,
                month=period.month,
                prev_month_revenue=prev_rev,
            )
        )

    return documents


# ─────────────────────────────────────────────
# 6. DEMO: In ví dụ output
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import json

    FILEPATH = r"data\documents\Khach hang.xlsx"
    df = pd.read_excel(FILEPATH, sheet_name="Khách hàng")
    df["Ngày"]      = pd.to_datetime(df["Ngày"])
    df["Tổng tiền"] = pd.to_numeric(df["Tổng tiền"], errors="coerce").fillna(0)
    df["Ghi nợ"]    = pd.to_numeric(df["Ghi nợ"],    errors="coerce").fillna(0)

    print("=" * 60)
    print("LAYER 1 — Transaction Document (3 ví dụ)")
    print("=" * 60)
    for _, row in df.head(3).iterrows():
        doc = serialize_transaction(row)
        print("\n📄 TEXT:")
        print(" ", doc["text"])
        print("🏷  METADATA:", doc["metadata"])
    
    for _, row in df.iterrows():
        saved_path = r"data\ingestions\transactions.jsonl"
        with open(saved_path, "a", encoding="utf-8") as f:
            json.dump(serialize_transaction(row), f, ensure_ascii=False)
            f.write("\n")

    print("\n" + "=" * 60)
    print("LAYER 2 — Customer Profile Document")
    print("=" * 60)
    sample_kh = df.groupby("Khách hàng").get_group(
        df.groupby("Khách hàng")["Tổng tiền"].sum().idxmax()
    )
    doc = serialize_customer_profile(sample_kh)
    print("\n📄 TEXT:")
    print(" ", doc["text"])
    print("🏷  METADATA:", doc["metadata"])
    
    for ten_kh, group in df.groupby("Khách hàng"):
        saved_path = r"data\ingestions\customers.jsonl"
        with open(saved_path, "a", encoding="utf-8") as f:
            json.dump(serialize_customer_profile(group), f, ensure_ascii=False)
            f.write("\n")

    print("\n" + "=" * 60)
    print("LAYER 3 — Period Summary Document")
    print("=" * 60)
    df["_ym"] = df["Ngày"].dt.to_period("M")
    first_month = df[df["_ym"] == sorted(df["_ym"].unique())[0]]
    doc = serialize_period_summary(first_month, year=2025, month=1)
    print("\n📄 TEXT:")
    print(" ", doc["text"])
    print("🏷  METADATA:", doc["metadata"])
    
    for period in sorted(df["_ym"].unique()):
        df_month = df[df["_ym"] == period]
        doc = serialize_period_summary(df_month, year=period.year, month=period.month)
        saved_path = r"data\ingestions\period_summaries.jsonl"
        with open(saved_path, "a", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
            f.write("\n")

    print("\n" + "=" * 60)
    total = len(df) + df["Khách hàng"].nunique() + df["_ym"].nunique()
    print(f"✅ Tổng documents sẽ được embed: ~{total:,}")
    print(f"   - Transaction  : {len(df):,}")
    print(f"   - Customer Profile: {df['Khách hàng'].nunique():,}")
    print(f"   - Period Summary  : {df['_ym'].nunique()}")
    print("=" * 60)
