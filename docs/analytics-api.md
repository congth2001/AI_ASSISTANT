# Analytics API

Tài liệu mô tả các endpoint `/api/v1/analytics/*`, đối chiếu với code ngày 2026-11-17: router `src/modules/analytics/presentation/router.py`, DTO `presentation/dto/analytics.py`, use case `application/use_cases/`, truy vấn `infrastructure/repositories/` (`dashboard_analytics_repository.py` cùng các module `analytics_scope.py`, `order_queries.py`, `order_ledger_queries.py`, `order_ledger_builder.py`, `customer_debt_queries.py`). Khi tài liệu mâu thuẫn với code, ưu tiên code.

Bảng nguồn và quy ước dấu công nợ: xem [data-model.md](data-model.md). Định nghĩa và giao diện của màn hình Tổng quan (insight, so sánh hai kỳ, độ mới dữ liệu): xem [../../docs/overview-insights.md](../../docs/overview-insights.md); tài liệu này không lặp lại phần đó.

## 1. Quy ước chung

- **Quyền**: mọi endpoint cần Bearer token và vai trò `staff` hoặc `admin` (`require_role("staff", "admin")`). `guest` bị từ chối.
- **Prefix**: `/api/v1/analytics`.
- **Khoảng ngày báo cáo** (nhóm bộ lọc dashboard): `date_from` bao gồm, `date_to` **loại trừ** (`[date_from, date_to)`), theo giờ nghiệp vụ Việt Nam (`Asia/Ho_Chi_Minh`). Cần `date_from < date_to`, nếu không trả lỗi validation `invalid_report_date_range`. `period` trong response trả `date_from`, `date_to`, `end_exclusive: true`, `timezone`.
- **Kỳ trước**: cùng số ngày, kết thúc đúng tại `date_from` (`DashboardFilters.previous_period()`), giữ nguyên các bộ lọc khác.
- **Tiền** là `Decimal` ở backend, JSON trả dưới dạng chuỗi số (ví dụ `"1250000.00"`); số lượng `Numeric(18,3)`. Không dùng float trong luồng dữ liệu.
- **Lỗi**: response `{"detail": ...}`; tham số sai (ngày, cursor, quá nhiều giá trị lọc, vượt trần dòng xuất file) là 422 validation; `order_not_found` và `customer_not_found` là 404. Router chỉ đổi lỗi *validation* của catalog thành 422; mọi lỗi khác (hạ tầng, bug) giữ nguyên status qua error handler chung (500), không bị che thành lỗi request.
- **Chỉ tính dữ liệu còn hiệu lực**: các truy vấn lọc `deleted_at IS NULL` trên hóa đơn, dòng hàng, khách và sổ công nợ.
- **Giới hạn tham số lặp lại** (`ward`, `village`, `category`, `product`, `customer_id`): tối đa 100 giá trị mỗi tham số, mỗi giá trị tối đa 200 ký tự; vượt giới hạn trả 422 (`too_many_filter_values`, `filter_value_too_long`).

### Phạm vi dữ liệu (`customer_scope`)

Mọi truy vấn dashboard (`summary`, `time-series`, `rankings`, `customer-overview`, `overview-insights`) dùng **một** định nghĩa phạm vi khách hàng (`infrastructure/repositories/analytics_scope.py`): khách **chưa xóa mềm** và khớp tùy chọn `customer_id`, `ward`, `village` (địa bàn hiện tại trong `customers`). Phạm vi áp lên bảng sự kiện bằng semi-join `customer_id IN (SELECT ... FROM customers WHERE ...)`, nên:

- khách đã xóa mềm bị loại ở **mọi** màn hình, kể cả khi không có bộ lọc khách/địa bàn (trước đây `summary` không loại);
- khách chỉ có hàng trả vẫn xuất hiện trong xếp hạng khách và `customer-overview` (doanh thu âm).

Doanh thu theo khách dùng chung subquery `revenue_movements` (xem mục 4), nên `summary.total_revenue`, tổng `rankings/customer` và `customer-overview.metrics.total_revenue` luôn khớp nhau với cùng bộ lọc.

### Bộ lọc dashboard dùng chung

Dùng cho `summary`, `time-series`, `time-series-comparison`, `rankings/{dimension}`, `customer-overview`, `overview-insights`.

| Tham số | Kiểu | Bắt buộc | Ghi chú |
| --- | --- | --- | --- |
| `date_from` | date | có | Bao gồm. |
| `date_to` | date | có | Loại trừ. |
| `customer_id` | UUID | không | Một khách. |
| `ward` | string, lặp lại được | không | Phường/xã (địa bàn hiện tại trong `customers`). |
| `village` | string, lặp lại được | không | Thôn/xóm. |
| `category` | string, lặp lại được | không | Danh mục sản phẩm. |
| `product` | string, lặp lại được | không | Tên sản phẩm. |

## 2. Danh sách endpoint

| Method | Đường dẫn | Mục đích |
| --- | --- | --- |
| GET | `/analytics/summary` | KPI và so sánh doanh thu với kỳ trước. |
| GET | `/analytics/time-series` | Chuỗi doanh thu/số hóa đơn theo grain. |
| GET | `/analytics/time-series-comparison` | Hai chuỗi cùng số ngày. |
| GET | `/analytics/rankings/{dimension}` | Xếp hạng khách hàng/sản phẩm/danh mục. |
| GET | `/analytics/filter-options` | Option cho các bộ lọc. |
| GET | `/analytics/data-freshness` | Độ mới dữ liệu. |
| GET | `/analytics/overview-insights` | Ba nhóm insight của Tổng quan. |
| GET | `/analytics/customer-overview` | Khách hàng, công nợ lũy kế, phân trang lai. |
| GET | `/analytics/customer-debt/export` | Xuất Excel công nợ. |
| GET | `/analytics/orders` | Danh sách hóa đơn. |
| GET | `/analytics/orders/export` | Xuất Excel nhật ký giao dịch của một khách. |
| GET | `/analytics/orders/{invoice_id}` | Chi tiết hóa đơn. |

Router khai báo `/orders/export` trước `/orders/{invoice_id}` để đường dẫn `export` không bị hiểu là `invoice_id`.

## 3. Chi tiết

### 3.1 `GET /analytics/summary`

Tham số: bộ lọc dashboard dùng chung.

Response `AnalyticsSummaryResponse`:

- `period`.
- `metrics`: `total_revenue`, `invoice_count`, `customer_count`, `average_invoice_value`, `net_debt_delta`.
- `comparison`: `previous_revenue`, `revenue_change`, `revenue_growth_percent` (làm tròn 2 chữ số `ROUND_HALF_UP`; `null` khi doanh thu kỳ trước bằng 0).

```http
GET /api/v1/analytics/summary?date_from=2026-11-01&date_to=2026-11-16
```

```json
{
  "period": {"date_from": "2026-11-01", "date_to": "2026-11-16", "end_exclusive": true, "timezone": "Asia/Ho_Chi_Minh"},
  "metrics": {"total_revenue": "125000000.00", "invoice_count": 310, "customer_count": 142, "average_invoice_value": "420000.00", "net_debt_delta": "18000000.00"},
  "comparison": {"previous_revenue": "100000000.00", "revenue_change": "25000000.00", "revenue_growth_percent": "25.00"}
}
```

(Số liệu trong ví dụ là minh họa.)

### 3.2 `GET /analytics/time-series`

Tham số: bộ lọc dùng chung và `grain` (`day` mặc định, `week`, `month`, `quarter`, `year`).

Response: `period`, `grain`, `items[]` gồm `period_start` (date), `revenue`, `invoice_count`. Nhóm bằng `date_trunc(grain, issued_at)`; điểm không có giao dịch không được tạo ở endpoint này.

### 3.3 `GET /analytics/time-series-comparison`

Tham số như `time-series`. Response: `period`, `previous_period`, `grain`, `items[]` gồm `period_start`, `period_end`, `previous_period_start`, `previous_period_end` (các `*_end` loại trừ), `revenue`, `previous_revenue`, `invoice_count`, `previous_invoice_count`. Chi tiết cách ghép ngày: xem [overview-insights.md](../../docs/overview-insights.md).

### 3.4 `GET /analytics/rankings/{dimension}`

- Path `dimension`: `customer`, `product`, `category`.
- Tham số: bộ lọc dùng chung, `limit` (1-100, mặc định 10), `offset` (>= 0).
- Response: `period`, `dimension`, `items[]` (`key`, `label`, `revenue`, `invoice_count`, `quantity`, `unit_name`; hai trường cuối có thể `null`), `total`, `limit`, `offset`.
- Sắp xếp `revenue` giảm dần, `label` tăng dần, rồi `key` tăng dần (khóa phụ cuối để phân trang offset ổn định khi trùng doanh thu và tên). Phân trang kiểu offset.
- `customer`: gồm cả khách chỉ có hàng trả; doanh thu theo `revenue_movements` (mục 4), `invoice_count` đếm hóa đơn bán phân biệt. `product`/`category`: theo dòng hàng, trừ dòng trả.

### 3.5 `GET /analytics/filter-options`

| Tham số | Ghi chú |
| --- | --- |
| `search` | Tối đa 100 ký tự; khớp chứa, không phân biệt hoa thường; `%` và `_` được escape (là ký tự thường, không phải wildcard). Áp cho khách, phường/xã, thôn/xóm, danh mục, sản phẩm. |
| `limit` | 1-200, mặc định 50. |
| `ward`, `village` | Lặp lại được (tối đa 100 giá trị); thu hẹp option khách hàng và thôn/xóm phụ thuộc. |

Response: `customers[]` (`value` = UUID, `label` = tên), `wards[]`, `villages[]`, `categories[]`, `products[]`. Danh sách khách sắp xếp theo tên rồi UUID.

### 3.6 `GET /analytics/data-freshness`

Không tham số. Response `latest_transaction_date`, `last_recorded_at` (đều có thể `null`), toàn hệ thống, không phụ thuộc bộ lọc. `last_recorded_at` không phải thời điểm ETL hoàn tất. Xem [overview-insights.md](../../docs/overview-insights.md).

### 3.7 `GET /analytics/overview-insights`

Bộ lọc dùng chung nhưng **từ chối** `category`/`product` (`overview_dimensions_unsupported`). Response gồm `period`, `previous_period`, `declining_customers`, `declining_customer_count`, `inactive_customer_count`, `declining_revenue_change`, `debt_customers`, `total_receivables`, `debtor_count`, `top_receivables`, `top_receivables_share_percent`, `ward_movements`. Ý nghĩa từng nhóm: xem [overview-insights.md](../../docs/overview-insights.md).

### 3.8 `GET /analytics/customer-overview`

Tham số: bộ lọc dùng chung, `limit` (1-100, mặc định 25), `cursor` (tối đa 1000 ký tự), `offset` (>= 0).

Response:

- `period`.
- `metrics`: `total_customers`, `purchasing_customers`, `debtor_customers`, `non_debtor_customers`, `total_revenue`, `invoice_count`, `receivables`, `advances`, `net_balance`, `debt_by_ward[]` (`ward_name`, `debtor_customers`, `receivables`; ward null hiển thị `Chưa xác định`, sắp xếp phải thu giảm dần).
- `items[]`: `key`, `label`, `ward_name`, `village_name`, `revenue`, `invoice_count`, `last_purchase_at`, `current_debt`.
- Khi có bộ lọc `category`/`product`: `revenue` = tổng dòng hàng khớp trừ dòng trả khớp của khách đó; `invoice_count`/`last_purchase_at` chỉ tính hóa đơn có dòng khớp. `current_debt`, `receivables`, `advances`, `net_balance` **không đổi** vì sổ công nợ không có chiều sản phẩm.
- Truy vấn: một lượt `GROUP BY` phường/xã cho toàn bộ chỉ số tổng và biểu đồ công nợ, một truy vấn cho trang dữ liệu; bộ lọc khách/địa bàn được đẩy xuống subquery số dư và doanh thu.
- `total` (bằng `metrics.total_customers`), `limit`, `next_cursor`, `has_more`.

**Phân trang lai**: thứ tự cố định `current_debt` giảm, `revenue` giảm, `label` tăng, `key` tăng. Dùng `next_cursor` (keyset, mã hóa base64 JSON của bốn khóa sắp xếp) để sang trang kế tiếp đã biết; dùng `offset` để nhảy trực tiếp. **Không gửi đồng thời** `cursor` và `offset`: lỗi `cursor_pagination_conflict`. Cursor hỏng trả 422 `invalid_customer_overview_cursor` (base64/JSON hỏng, thiếu khóa, sai kiểu, số không hợp lệ, `key` không phải UUID) hoặc `invalid_cursor_values` (số không hữu hạn, vượt `numeric(18,2)`, thang quá nhỏ, `label` rỗng). Repository lấy `limit + 1` dòng để xác định `has_more`; `next_cursor` chỉ có khi còn trang sau.

```http
GET /api/v1/analytics/customer-overview?date_from=2026-11-01&date_to=2026-11-16&limit=25
GET /api/v1/analytics/customer-overview?date_from=2026-11-01&date_to=2026-11-16&limit=25&cursor=<next_cursor>
GET /api/v1/analytics/customer-overview?date_from=2026-11-01&date_to=2026-11-16&limit=25&offset=100
```

### 3.9 `GET /analytics/customer-debt/export`

Trả file `.xlsx` (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`), `Cache-Control: no-store`, tên `cong-no-khach-hang-YYYYMMDD-HHMMSS.xlsx` theo giờ Việt Nam.

| Tham số | Ghi chú |
| --- | --- |
| `date_from`, `date_to` | Tùy chọn, **bao gồm cả hai đầu**; `date_from <= date_to` (`invalid_export_date_range`). Bỏ trống: cộng toàn bộ sổ. |
| `customer_id` | UUID, lặp lại được. |
| `ward` | Lặp lại được. |
| `positive_debt_only` | Mặc định `false`. |
| `sheet_mode` | `single` (mặc định), `village`, `ward`. `village` bắt buộc có ít nhất một `ward` (`village_ward_required`). Luôn có sheet `All`. |

Công nợ cộng các bút toán `customer_debt_transactions` có `occurred_at` trong khoảng; sắp xếp công nợ giảm dần (theo tên rồi UUID khi bằng nhau). 

**Giới hạn dòng**: tối đa 200.000 dòng dữ liệu mỗi sheet và 500.000 dòng cho cả workbook (`MAX_SHEET_DATA_ROWS`/`MAX_WORKBOOK_DATA_ROWS` trong `domain/models/export_limits.py`). Truy vấn lấy tối đa 200.001 dòng rồi dừng, nên file quá lớn bị từ chối **trước** khi nạp hết và dựng workbook: 422 `customer_debt_row_limit` (một sheet vượt trần) hoặc `export_workbook_row_limit` (tổng vượt trần; chế độ `village`/`ward` ghi mỗi khách hai lần: sheet `All` và sheet nhóm).

**Ô văn bản**: lưu kiểu chuỗi tường minh (`data_type = "s"`), không bao giờ là công thức; giá trị hiển thị không bị đổi (không thêm dấu `'`). Ô bắt đầu bằng `= + - @`, tab hoặc xuống dòng được đặt `quotePrefix`. Tên sheet bỏ ký tự cấm, bỏ dấu `'`/khoảng trắng ở đầu/cuối (cả sau khi cắt 31 ký tự) và tránh tên dành riêng `History`.

### 3.10 `GET /analytics/orders`

| Tham số | Ghi chú |
| --- | --- |
| `date_from`, `date_to` | Tùy chọn; `date_to` **loại trừ**; nếu có cả hai thì `date_from < date_to`. |
| `invoice_number` | Tối đa 100 ký tự; khớp chứa, không phân biệt hoa thường, có escape ký tự đặc biệt. |
| `customer_id` | UUID. |
| `ward`, `village` | Lặp lại được. Mặc định lọc theo địa bàn **snapshot** trên hóa đơn. |
| `customer_geography` | `true` để lọc theo địa bàn hiện tại của `customers` (cùng định nghĩa phạm vi khách như dashboard, gồm loại khách đã xóa mềm). |
| `limit` | 1-100, mặc định 20. |
| `offset` | >= 0. |

Response `OrderPageResponse`: `items[]` (`invoice_id`, `invoice_number`, `issued_at`, `customer_name`, `customer_ward_name`, `customer_village_name`, `invoice_total_amount`, `line_count`), `total`, `limit`, `offset`. Sắp xếp `issued_at`, `invoice_number`, `invoice_id` giảm dần (mới nhất trước). Phân trang offset. `line_count` chỉ được tính cho các hóa đơn của trang hiện tại (sau LIMIT/OFFSET), không gom toàn bảng dòng hàng.

### 3.11 `GET /analytics/orders/{invoice_id}`

Path `invoice_id` dài 1-200 ký tự. Response `OrderDetailResponse`: `invoice_id`, `invoice_number`, `issued_at`, `customer_name`, `customer_address_detail`, `customer_ward_name`, `customer_village_name`, `invoice_total_amount`, `lines[]` (`line_number`, `product_name`, `product_category_name`, `unit_name`, `unit_price`, `quantity`, `line_amount`; sắp xếp theo `line_number`). Không thấy hóa đơn: 404 `order_not_found`.

### 3.12 `GET /analytics/orders/export`

Trả `.xlsx`, tên `chi-tiet-giao-dich-cong-no-YYYYMMDD-HHMMSS.xlsx`. Giữ nguyên 10 cột mẫu iShopman.

| Tham số | Ghi chú |
| --- | --- |
| `customer_id` | **Bắt buộc**, UUID. Không tìm thấy khách (hoặc đã xóa mềm): 404 `customer_not_found`. |
| `date_from`, `date_to` | Tùy chọn, **bao gồm cả hai đầu** (code cộng thêm một ngày để loại trừ khi truy vấn). |
| `invoice_number` | Tùy chọn; chỉ **ẩn dòng** có số phiếu không chứa chuỗi này, số dư cộng dồn vẫn tính cả dòng bị ẩn. |
| `ward`, `village` | Giữ để tương thích nhưng **bị bỏ qua khi có `customer_id`** (luôn có với endpoint này): khách đã được chọn thì số dư đầu kỳ, thu nợ, bán và trả đều lấy cùng một khách, không còn lọc theo snapshot địa bàn trên hóa đơn. |

**Nguồn số liệu**: dòng chuyển động (`movement`) và **nợ cộng dồn** lấy từ sổ cái `customer_debt_transactions` (không dùng `sales_invoices.debt_delta_amount`). Hóa đơn (`XB%`) và phiếu trả (`NT%`) chỉ cung cấp chi tiết hiển thị (tên hàng, đơn giá, số lượng, phần thanh toán):

- Số dư đầu kỳ = tổng các bút toán `opening` cộng mọi bút toán có `occurred_at < date_from` (chỉ `opening` khi bỏ trống `date_from`); không bao giờ gồm bút toán từ cuối khoảng trở đi. Số dư cuối cùng luôn bằng số dư sổ cái.
- `Thu nợ`: bút toán `receipt` (`Thanh toán` = giá trị tuyệt đối, `Ghi nợ` = 0).
- `Nhập trả`: ghép phiếu trả với bút toán `sales_return` theo `SalesReturn.source_id = source_id`; `Ghi nợ` = bút toán (âm).
- `Xuất bán`: sổ cái lưu mã hóa đơn gốc chứ không phải `invoice_id`, nên ghép theo (khách, `issued_at = occurred_at`); `Ghi nợ` = bút toán khớp, `Thanh toán` = tổng hóa đơn trừ ghi nợ. Nhiều hóa đơn cùng khách và cùng thời điểm: tổng bút toán gán cho hóa đơn đầu tiên (theo số hóa đơn), các hóa đơn còn lại movement 0.
- Hóa đơn/phiếu trả không có bút toán (hóa đơn trả đủ, phiếu 0 đồng) vẫn hiện với movement 0; bút toán không có chứng từ hiển thị được vẫn hiện thành một dòng (số phiếu = `source_id`) và vẫn làm đổi số dư.
- Bộ lọc địa bàn (chỉ khi không có `customer_id`) dùng địa bàn hiện tại của `customers`, đồng nhất cho mọi nguồn.

Giới hạn tối đa 200.000 dòng (`order_ledger_row_limit`, 422); mỗi truy vấn con lấy tối đa 200.001 dòng nên file quá lớn bị từ chối trước khi dựng workbook.

## 4. Quy tắc tính

- **Doanh thu thuần (không lọc sản phẩm/danh mục)** = tổng `sales_invoices.invoice_total_amount` trong kỳ + tổng `customer_debt_transactions.amount` của `source_type = 'sales_return'` trong kỳ (các dòng này đã âm). Không cộng `line_amount` thay tổng hóa đơn.
- **Khi có `category` hoặc `product`**: `summary`, `time-series`, `rankings` và `customer-overview` đều tính theo dòng hàng: tổng `sales_invoice_lines.line_amount` khớp trừ tổng `sales_return_lines.line_amount` khớp (bảng trả hàng theo ngày `returned_at`); không cộng `invoice_total_amount` của cả hóa đơn và không lấy toàn sổ hàng trả. `invoice_count` trong chuỗi `time-series` đếm số chứng từ phân biệt (bán và trả); trong `summary`/`rankings/customer`/`customer-overview` chỉ đếm hóa đơn bán có dòng khớp.
- **`revenue_movements`**: subquery dùng chung của `summary.total_revenue`, `rankings/customer`, `customer-overview` và `overview-insights`: các dòng (`customer_id`, `occurred_at`, `amount`, `invoice_id`) gồm hóa đơn bán và hàng trả của khách trong phạm vi; không lọc dòng hàng thì dùng `invoice_total_amount` + bút toán `sales_return`, có lọc thì dùng dòng bán và dòng trả khớp.
- **`invoice_count`, `customer_count`, `average_invoice_value`** trong `summary` tính trên hóa đơn bán còn hiệu lực; trung bình là trung bình `invoice_total_amount` trước trừ hàng trả.
- **`net_debt_delta`** = tổng có dấu `customer_debt_transactions.amount` của khách trong phạm vi có `occurred_at` trong kỳ (mọi `source_type`). Sổ công nợ không có chiều sản phẩm, nên **bộ lọc `category`/`product` không làm đổi `net_debt_delta`** (vẫn là biến động công nợ của các khách trong phạm vi, không phải của riêng sản phẩm đó); trường vẫn là chuỗi số không null để giữ hợp đồng với frontend.
- **Công nợ lũy kế** (`customer-overview`, insight): tổng `amount` của mọi dòng sổ có `occurred_at < date_to`, theo từng khách. `receivables` = tổng phần dương của số dư từng khách; `advances` = tổng phần âm đổi dấu (khách ứng trước/dư có); `net_balance` = tổng số dư có dấu; khách có số dư > 0 là khách còn nợ. Không dùng `sales_invoices.debt_delta_amount`.
- **So sánh hai kỳ**: `revenue_change = revenue - previous_revenue`; `revenue_growth_percent = change * 100 / previous_revenue`, làm tròn 2 chữ số, `null` khi kỳ trước bằng 0.
- **Múi giờ**: `issued_at`, `returned_at`, `occurred_at` là `timestamp` không timezone được hiểu là giờ Việt Nam; ngày so sánh với `date_from`/`date_to` trực tiếp; tên file export dùng `Asia/Ho_Chi_Minh`.
- **Địa bàn**: dashboard lọc theo `customers.ward_name`/`village_name` (hiện tại); riêng `orders` mặc định dùng snapshot trên hóa đơn (trừ khi `customer_geography=true`). Xuất nhật ký giao dịch không dùng snapshot (xem 3.12).

## 5. Mã kiểm tra

```powershell
cd D:\AI_ASSISTANT\backend
.\env\Scripts\python.exe -m pytest tests\unit\test_dashboard_analytics.py tests\unit\test_dashboard_analytics_api.py tests\unit\test_overview_analytics.py tests\unit\test_analytics_hardening.py

# Truy vấn thật trên PostgreSQL (schema tạm dựng từ ORM, rollback cuối test):
$env:AI_ANALYTICS_TEST_DSN = "postgresql+asyncpg://postgres@localhost:5432/ai_assistant_test"
.\env\Scripts\python.exe -m pytest tests\integrate\test_analytics_queries.py tests\integrate\test_overview_queries.py
```

`test_analytics_queries.py` kiểm chứng trên PostgreSQL thật: `summary`, xếp hạng khách và `customer-overview` cho cùng tổng doanh thu (có và không có bộ lọc sản phẩm), khách xóa mềm bị loại, khách chỉ trả hàng có mặt, phân trang offset không trùng khi hòa khóa, cursor và offset trả cùng trang, số dư nhật ký bằng sổ cái, escape `%`/`_`.
