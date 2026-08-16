# Business ETL (iShopman MDB)

Module này là adapter hạ tầng của project chính, không phải Python project
hay virtual environment riêng. Chạy lệnh từ repository root:

```bat
python -m etl_business.shop_data_extractor.cli inspect
python -m etl_business.shop_data_extractor.cli extract
python run_business_etl.py
```

Luồng dữ liệu:

```text
iShopman.mdb
  -> etl_business/stats/extract.yml (source column -> canonical column)
  -> data/etl/csv/*.csv + data/etl/ishopman_extract.xlsx
  -> data/documents/Khach_hang.xlsx + Hang_hoa.xlsx
  -> SyncBusinessDataUseCase -> PostgreSQL
```

Lệnh `run_business_etl.py` là entrypoint production cho cron: nó khóa chống
hai job chạy chồng, extract ZIP/MDB, áp dụng rule normalize nội bộ, ghi artifact audit,
upsert idempotent và trả exit code khác 0 khi bất kỳ bước nào lỗi.

Hai notebook `normalize_customer.ipynb` và `normalize_good.ipynb` chỉ là nguồn
tham khảo ban đầu. Production ETL không đọc hoặc execute notebook: thuật toán
nằm trong `etl_business/normalization.py`, bảng alias đã được version hóa tại
`etl_business/stats/product_aliases.json`.

Bốn dataset `customers`, `sales`, `sale_items`, `products` phải được map sang
các cột canonical sau; pipeline sẽ fail-fast nếu thiếu cột hoặc sai foreign key:

- `customers`: `customer_id`, `customer_name`; tùy chọn `address_detail`, `village_name`, `ward_name`.
- `sales`: `invoice_id`, `invoice_number`, `customer_id`, `issued_at`, `invoice_total_amount`; tùy chọn `debt_delta_amount`.
- `sale_items`: `invoice_id`, `product_id`, `quantity`, `unit_price`, `line_amount`.
- `products`: `product_id`, `product_name`, `unit_name`; tùy chọn `product_category_name`.

Cấu hình runtime nằm trong block `etl` của `config/local.yml`; xem
`config/local.example` để biết các field hỗ trợ. ETL không đọc `.env` riêng.

Codebase dùng để đọc file `iShopman.mdb` (có password), phát hiện schema và export
các dataset nghiệp vụ ra **CSV + Excel**.

## Output

Sau khi chạy `extract`:

```text
output/
├── csv/
│   ├── products.csv
│   ├── customers.csv
│   ├── sales.csv
│   ├── sale_items.csv
│   └── inventory.csv
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
output/schema_profile.xlsx
output/schema_profile.json
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
```

Khi `source_path` là thư mục, mỗi lần chạy pipeline sẽ chọn file `*.zip`
có thời gian `last modified` mới nhất ngay trong thư mục đó. Kết quả job ghi
rõ path file đã chọn trong field `source`.

Không commit `config/local.yml`; chỉ commit `config/local.example`.

## Lần chạy đầu

### 1. Inspect database

```bat
scripts\run_inspect.bat
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

- `products`: danh mục hàng hóa.
- `customers`: khách hàng.
- `sales`: hóa đơn / giao dịch bán hàng.
- `sale_items`: chi tiết hóa đơn.
- `inventory`: tồn kho.

Đây là các nhóm phù hợp cho bước tiếp theo khi ingest sang PostgreSQL/RAG.
Các bảng khác có thể thêm vào `extra_tables`.

## Encoding CSV

CSV được xuất bằng `UTF-8 with BOM` (`utf-8-sig`) để Excel trên Windows mở
tiếng Việt đúng hơn.

## An toàn dữ liệu

Connection MDB sử dụng `READONLY=1`; extractor không ghi ngược vào database Access.

## Task Scheduler

Sau khi mapping đã ổn định, Windows Task Scheduler có thể chạy:

```text
D:\AI_assistant\etl_business\scripts\run_sync.bat
```

mỗi ngày sau khi ZIP backup đã được ghi xong. Task Scheduler nên cấu
hình `Start in` là `D:\AI_assistant`; stdout/stderr có thể được redirect bởi
wrapper giám sát của hệ thống.
