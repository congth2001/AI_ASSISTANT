# Analytics API

Tài liệu mô tả các endpoint `/api/v1/analytics/*`, đối chiếu với code ngày 2026-11-17: router `src/modules/analytics/presentation/router.py`, DTO `presentation/dto/analytics.py`, use case `application/use_cases/`, truy vấn `infrastructure/repositories/dashboard_analytics_repository.py`. Khi tài liệu mâu thuẫn với code, ưu tiên code.

Bảng nguồn và quy ước dấu công nợ: xem [data-model.md](data-model.md). Định nghĩa và giao diện của màn hình Tổng quan (insight, so sánh hai kỳ, độ mới dữ liệu): xem [../../docs/overview-insights.md](../../docs/overview-insights.md); tài liệu này không lặp lại phần đó.

## 1. Quy ước chung

- **Quyền**: mọi endpoint cần Bearer token và vai trò `staff` hoặc `admin` (`require_role("staff", "admin")`). `guest` bị từ chối.
- **Prefix**: `/api/v1/analytics`.
- **Khoảng ngày báo cáo** (nhóm bộ lọc dashboard): `date_from` bao gồm, `date_to` **loại trừ** (`[date_from, date_to)`), theo giờ nghiệp vụ Việt Nam (`Asia/Ho_Chi_Minh`). Cần `date_from < date_to`, nếu không trả lỗi validation `invalid_report_date_range`. `period` trong response trả `date_from`, `date_to`, `end_exclusive: true`, `timezone`.
- **Kỳ trước**: cùng số ngày, kết thúc đúng tại `date_from` (`DashboardFilters.previous_period()`), giữ nguyên các bộ lọc khác.
- **Tiền** là `Decimal` ở backend, JSON trả dưới dạng chuỗi số (ví dụ `"1250000.00"`); số lượng `Numeric(18,3)`. Không dùng float trong luồng dữ liệu.
- **Lỗi**: response `{"detail": ...}`; lỗi nghiệp vụ như ngày sai, cursor sai là 4xx validation, `order_not_found` là 404.
- **Chỉ tính dữ liệu còn hiệu lực**: các truy vấn lọc `deleted_at IS NULL` trên hóa đơn, dòng hàng, khách và sổ công nợ.

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
- Sắp xếp `revenue` giảm dần rồi `label` tăng dần. Phân trang kiểu offset.

### 3.5 `GET /analytics/filter-options`

| Tham số | Ghi chú |
| --- | --- |
| `search` | Tối đa 100 ký tự; khách hàng lọc `ILIKE %search%`. |
| `limit` | 1-200, mặc định 50. |
| `ward`, `village` | Lặp lại được; thu hẹp option khách hàng và thôn/xóm phụ thuộc. |

Response: `customers[]` (`value` = UUID, `label` = tên), `wards[]`, `villages[]`, `categories[]`, `products[]`. Danh sách khách sắp xếp theo tên.

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
- `total` (bằng `metrics.total_customers`), `limit`, `next_cursor`, `has_more`.

**Phân trang lai**: thứ tự cố định `current_debt` giảm, `revenue` giảm, `label` tăng, `key` tăng. Dùng `next_cursor` (keyset, mã hóa base64 JSON của bốn khóa sắp xếp) để sang trang kế tiếp đã biết; dùng `offset` để nhảy trực tiếp. **Không gửi đồng thời** `cursor` và `offset`: lỗi `cursor_pagination_conflict`. Cursor hỏng trả `invalid_customer_overview_cursor` hoặc `invalid_cursor_values`. Repository lấy `limit + 1` dòng để xác định `has_more`; `next_cursor` chỉ có khi còn trang sau.

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

Công nợ cộng các bút toán `customer_debt_transactions` có `occurred_at` trong khoảng; sắp xếp công nợ giảm dần (theo tên khi bằng nhau). Vượt giới hạn dòng Excel trả `customer_debt_row_limit`.

### 3.10 `GET /analytics/orders`

| Tham số | Ghi chú |
| --- | --- |
| `date_from`, `date_to` | Tùy chọn; `date_to` **loại trừ**; nếu có cả hai thì `date_from < date_to`. |
| `invoice_number` | Tối đa 100 ký tự; khớp chứa, không phân biệt hoa thường, có escape ký tự đặc biệt. |
| `customer_id` | UUID. |
| `ward`, `village` | Lặp lại được. Mặc định lọc theo địa bàn **snapshot** trên hóa đơn. |
| `customer_geography` | `true` để lọc theo địa bàn hiện tại của `customers` (và loại khách đã xóa mềm). |
| `limit` | 1-100, mặc định 20. |
| `offset` | >= 0. |

Response `OrderPageResponse`: `items[]` (`invoice_id`, `invoice_number`, `issued_at`, `customer_name`, `customer_ward_name`, `customer_village_name`, `invoice_total_amount`, `line_count`), `total`, `limit`, `offset`. Sắp xếp `issued_at`, `invoice_number`, `invoice_id` giảm dần (mới nhất trước). Phân trang offset.

### 3.11 `GET /analytics/orders/{invoice_id}`

Path `invoice_id` dài 1-200 ký tự. Response `OrderDetailResponse`: `invoice_id`, `invoice_number`, `issued_at`, `customer_name`, `customer_address_detail`, `customer_ward_name`, `customer_village_name`, `invoice_total_amount`, `lines[]` (`line_number`, `product_name`, `product_category_name`, `unit_name`, `unit_price`, `quantity`, `line_amount`; sắp xếp theo `line_number`). Không thấy hóa đơn: 404 `order_not_found`.

### 3.12 `GET /analytics/orders/export`

Trả `.xlsx`, tên `chi-tiet-giao-dich-cong-no-YYYYMMDD-HHMMSS.xlsx`.

| Tham số | Ghi chú |
| --- | --- |
| `customer_id` | **Bắt buộc**, UUID. |
| `date_from`, `date_to` | Tùy chọn, **bao gồm cả hai đầu** (code cộng thêm một ngày để loại trừ khi truy vấn). |
| `invoice_number`, `ward`, `village` | Tùy chọn; áp dụng địa bàn snapshot. |

Workbook hợp nhất `Xuất bán` (hóa đơn có số bắt đầu `XB`), `Nhập trả` (`NT`) và `Thu nợ` (`receipt`), có nợ cộng dồn mang số dư đầu kỳ. Vượt giới hạn dòng Excel trả `order_ledger_row_limit`.

## 4. Quy tắc tính

- **Doanh thu thuần (không lọc sản phẩm/danh mục)** = tổng `sales_invoices.invoice_total_amount` trong kỳ + tổng `customer_debt_transactions.amount` của `source_type = 'sales_return'` trong kỳ (các dòng này đã âm). Không cộng `line_amount` thay tổng hóa đơn.
- **Khi có `category` hoặc `product`**: `summary` và `time-series` tính theo dòng hàng: tổng `sales_invoice_lines.line_amount` trừ tổng `sales_return_lines.line_amount` (bảng trả hàng theo ngày `returned_at`); `invoice_count` trong chuỗi đếm số chứng từ phân biệt (bán và trả).
- **`invoice_count`, `customer_count`, `average_invoice_value`** trong `summary` tính trên hóa đơn bán còn hiệu lực; trung bình là trung bình `invoice_total_amount` trước trừ hàng trả.
- **`net_debt_delta`** = tổng có dấu `customer_debt_transactions.amount` có `occurred_at` trong kỳ (mọi `source_type`).
- **Công nợ lũy kế** (`customer-overview`, insight): tổng `amount` của mọi dòng sổ có `occurred_at < date_to`, theo từng khách. `receivables` = tổng phần dương của số dư từng khách; `advances` = tổng phần âm đổi dấu (khách ứng trước/dư có); `net_balance` = tổng số dư có dấu; khách có số dư > 0 là khách còn nợ. Không dùng `sales_invoices.debt_delta_amount`.
- **So sánh hai kỳ**: `revenue_change = revenue - previous_revenue`; `revenue_growth_percent = change * 100 / previous_revenue`, làm tròn 2 chữ số, `null` khi kỳ trước bằng 0.
- **Múi giờ**: `issued_at`, `returned_at`, `occurred_at` là `timestamp` không timezone được hiểu là giờ Việt Nam; ngày so sánh với `date_from`/`date_to` trực tiếp; tên file export dùng `Asia/Ho_Chi_Minh`.
- **Địa bàn**: dashboard lọc theo `customers.ward_name`/`village_name` (hiện tại); riêng `orders` mặc định dùng snapshot trên hóa đơn (trừ khi `customer_geography=true`).

## 5. Mã kiểm tra

```powershell
cd D:\AI_ASSISTANT\backend
.\env\Scripts\python.exe -m pytest tests\unit\test_dashboard_analytics.py tests\unit\test_dashboard_analytics_api.py tests\unit\test_overview_analytics.py
```
