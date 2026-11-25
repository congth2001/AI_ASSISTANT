# Business ETL (iShopman MDB)

Module này là adapter hạ tầng của project chính, không phải Python project
hay virtual environment riêng. Chạy lệnh từ thư mục `backend/` (mọi đường dẫn
tương đối bên dưới tính từ đây; các script `.bat` cũng `cd` về `backend/`):

```bat
.\env\Scripts\python.exe -m etl_business.shop_data_extractor.cli inspect
.\env\Scripts\python.exe -m etl_business.shop_data_extractor.cli extract
.\env\Scripts\python.exe run_business_etl.py
```

Luồng dữ liệu:

```text
iShopman.mdb (hoặc ZIP chứa MDB)
  -> etl_business/stats/extract.yml (source column -> canonical column)
  -> data/etl/csv/*.csv + data/etl/ishopman_extract.xlsx
  -> normalization.py (alias sản phẩm, alias phường/xã)
  -> data/documents/Khach_hang.xlsx, Hang_hoa.xlsx, Cong_no.xlsx,
     Tra_hang.xlsx, Chi_tiet_tra_hang.xlsx
  -> SyncBusinessDataUseCase -> PostgreSQL
```

ETL không cập nhật Milvus hay cache Redis.

Đồng bộ PostgreSQL chạy trong một transaction và từ chối snapshot hóa đơn/công
nợ/trả hàng rỗng hoặc giảm quá 30% so với dữ liệu đang hoạt động (tránh export
lỗi xóa mềm toàn bộ dữ liệu). Chỉ khi chắc chắn mới thêm `--allow-shrink` cho
`run_business_etl.py`, `sync_business_data.py` hoặc `shop_data_extractor.cli run`.
`run_business_etl.py` ghi 5 file snapshot vào thư mục tạm `.staging-*` trong
`snapshot_dir` và chỉ thay file thật (`os.replace`) sau khi đồng bộ PostgreSQL thành
công; snapshot bị guard từ chối không ghi đè bộ file tốt gần nhất.
`sync_business_data.py` dùng cùng file khóa `etl.lock_path`, nên không chạy chồng
với job cron. Use case nhận tên cột canonical tiếng Anh; header tiếng Việt của
file Excel được ánh xạ tại `snapshot_columns.py`. Lỗi xóa cache Redis chỉ được log.

Lệnh `run_business_etl.py` là entrypoint production cho cron: nó khóa chống
hai job chạy chồng, extract ZIP/MDB, áp dụng rule normalize nội bộ, ghi artifact audit,
upsert idempotent và trả exit code khác 0 khi bất kỳ bước nào lỗi.

Thuật toán chuẩn hóa nằm trong `etl_business/normalization.py`; bảng alias được
version hóa tại `etl_business/stats/product_aliases.json` và
`etl_business/stats/customer_ward_aliases.json`.

Ledger công nợ được dựng từ bốn nguồn có dấu: `phaithu_dauky`
và `exim_export_invoice.money_debit` là số dương; `receipt_debt.invoice_val`
và phiếu nhập trả `NT` là số âm. PostgreSQL reconcile theo khóa
`(source_type, source_id)` và soft-delete giao dịch biến mất khỏi full snapshot.

Doanh thu tổng thể/theo khách hàng/địa bàn/thời gian là **doanh thu thuần**:
doanh thu bán từ `sales_invoices.invoice_total_amount` cộng các giao dịch âm
`customer_debt_transactions.amount` có `source_type = 'sales_return'`, với cùng
khoảng thời gian. Chi tiết nhập trả được trích từ
`exim_import_invoice_details` vào `sales_return_lines`. Doanh thu và số lượng
theo sản phẩm/danh mục là số thuần: dòng bán trừ dòng nhập trả theo cùng sản
phẩm, danh mục, đơn vị và khoảng ngày.

Tên xã của khách hàng được canonicalize trước khi tạo
`customer_identity_key`, theo mapping versioned tại
`etl_business/stats/customer_ward_aliases.json`. Giá trị không rỗng ngoài
danh sách được map thành `Khác`; giá trị rỗng được giữ là `NULL`.

Sáu dataset sau là bắt buộc và phải được map sang các cột canonical; pipeline
fail-fast nếu thiếu dataset, thiếu cột hoặc sai foreign key (`pipeline.py`):

- `customers`: `customer_id`, `customer_name`; tùy chọn `address_detail`, `village_name`, `ward_name`.
- `sales`: `invoice_id`, `invoice_number`, `customer_id`, `issued_at`, `invoice_total_amount`; tùy chọn `debt_delta_amount`.
- `sale_items`: `invoice_id`, `product_id`, `quantity`, `unit_price`, `line_amount`.
- `products`: `product_id`, `product_name`, `unit_name`; tùy chọn `product_category_name`.
- `sales_returns`: `source_id`, `return_number`, `customer_id`, `occurred_at`, `return_total_amount`, `amount`.
- `sales_return_items`: `source_line_id`, `source_id`, `product_id`, `quantity`, `unit_price`, `line_amount`.

`extract.yml` còn khai báo `product_categories` và `debt_receipts` (phiếu thu nợ
cho sổ công nợ).

Cấu hình runtime nằm trong block `etl` của `config/local.yml`; xem
`config/local.example` để biết các field hỗ trợ. ETL không đọc `.env` riêng.

Codebase dùng để đọc file `iShopman.mdb` (có password), phát hiện schema và export
các dataset nghiệp vụ ra **CSV + Excel**.

## Output

Sau khi chạy `extract`, kết quả nằm trong `etl.output_dir` (mặc định `data/etl`):

```text
data/etl/
├── csv/
│   ├── customers.csv
│   ├── debt_receipts.csv
│   ├── product_categories.csv
│   ├── products.csv
│   ├── sale_items.csv
│   ├── sales.csv
│   ├── sales_return_items.csv
│   └── sales_returns.csv
├── ishopman_extract.xlsx
└── extract_manifest.csv
```

Workbook `ishopman_extract.xlsx` chứa một sheet cho từng dataset và `_manifest`
ghi nguồn table, số dòng, số cột, trạng thái extract.

## Tại sao có bước inspect?

Tên bảng/cột thực tế của iShopman có thể không giống tên nghiệp vụ. Code không
được phép tự giả định sai schema. Vì vậy lần đầu:

```bat
    etl_business\scripts\run_inspect.bat
```

sẽ sinh:

```text
data/etl/schema_profile.xlsx
data/etl/schema_profile.json
```

`schema_profile.xlsx` gồm:
- `Tables`: danh sách table, row count, số cột.
- `Columns`: toàn bộ column/type.
- `Samples`: 3 record mẫu mỗi table ở dạng JSON.

Dựa vào profile, sửa `etl_business/stats/extract.yml` để trỏ chính xác
table/column cần lấy.

## Yêu cầu

- Windows 10/11 hoặc Windows Server.
- Python 3.11.
- Microsoft Access Database Engine / Access ODBC Driver có driver:
  `Microsoft Access Driver (*.mdb, *.accdb)`.
- Kiến trúc Python và ODBC driver phải cùng bitness (thường x64).

Kiểm tra driver:

```python
import pyodbc
print(pyodbc.drivers())
```

Phải thấy:

```text
Microsoft Access Driver (*.mdb, *.accdb)
```

## Setup

```bat
etl_business\scripts\setup.bat
```

Sửa block `etl` trong `config/local.yml`:

```yaml
etl:
  source_path: D:\Backup
  mdb_member: iShopman.mdb
  mdb_password: "<password>"
  output_dir: data/etl
  snapshot_dir: data/documents
  extract_config_path: etl_business/stats/extract.yml
  product_aliases_path: etl_business/stats/product_aliases.json
  lock_path: data/etl/business-etl.lock
  # Tùy chọn, có default:
  # customer_ward_aliases_path: etl_business/stats/customer_ward_aliases.json
  # opening_balance_date: "2019-01-01"
```

Khi `source_path` là thư mục, mỗi lần chạy pipeline sẽ chọn file `*.zip`
có thời gian `last modified` mới nhất ngay trong thư mục đó. Kết quả job ghi
rõ path file đã chọn trong field `source`.

Không commit `config/local.yml`; chỉ commit `config/local.example`.

## Lần chạy đầu

### 1. Inspect database

```bat
etl_business\scripts\run_inspect.bat
```

### 2. Xác định mapping

Ví dụ profile cho thấy:

```text
Table: tbl_Item
Columns:
- ItemID
- ItemCode
- ItemName
- SalePrice
```

thì sửa:

```yaml
datasets:
  products:
    table: tbl_Item
    columns:
      product_id: ItemID
      product_code: ItemCode
      product_name: ItemName
      sale_price: SalePrice
```

Khi `columns: {}` thì export toàn bộ cột nguyên bản.

### 3. Extract

```bat
    etl_business\scripts\run_extract.bat
```

## Những dataset nghiệp vụ được chuẩn bị sẵn

- `products`, `product_categories`: hàng hóa và danh mục.
- `customers`: khách hàng.
- `sales`, `sale_items`: hóa đơn bán và dòng hàng.
- `sales_returns`, `sales_return_items`: phiếu nhập trả và dòng trả.
- `debt_receipts`: phiếu thu nợ.

Chưa có dataset tồn kho. Các bảng khác có thể thêm vào `extra_tables`.

## Encoding CSV

CSV được xuất bằng `UTF-8 with BOM` (`utf-8-sig`) để Excel trên Windows mở
tiếng Việt đúng hơn.

## An toàn dữ liệu

Connection MDB sử dụng `READONLY=1`; extractor không ghi ngược vào database Access.

## Task Scheduler

Sau khi mapping đã ổn định, Windows Task Scheduler có thể chạy:

```text
D:\AI_ASSISTANT\backend\etl_business\scripts\run_sync.bat
```

mỗi ngày sau khi ZIP backup đã được ghi xong. Task Scheduler nên cấu
hình `Start in` là `D:\AI_ASSISTANT\backend`; stdout/stderr có thể được redirect bởi
wrapper giám sát của hệ thống.
