# Small Text-to-SQL Execution Benchmark

Bộ benchmark nhỏ gồm 26 câu hỏi có ground truth xác định trên một PostgreSQL fixture cô lập. Mục tiêu chính là đo:

```text
execution result accuracy = số case có kết quả SQL đúng / tổng số case
```

## Thành phần

- `datasets/business_sql_small.jsonl`: câu hỏi, SQL tham chiếu, kết quả chuẩn, kết quả thay thế được chấp nhận (`accepted_results`) và quy tắc nghiệp vụ.
- `fixtures/business_sql_small.sql`: dữ liệu tổng hợp cố định, chỉ tạo bảng tạm trong session benchmark.
- `generate_predictions.py`: sinh prediction bằng pipeline Text-to-SQL thật (gọi LLM).
- `predictions/example_predictions.jsonl`: contract đầu vào mẫu cho SQL do agent sinh.
- `run_execution_eval.py`: kiểm chứng ground truth, kiểm tra an toàn, chạy SQL và xuất báo cáo.

## Quy tắc nghiệp vụ được kiểm tra

Định nghĩa bám theo prompt sinh SQL (`assistant/application/prompts/sql_prompts.py`), metric rules trong `schema_linker.py`, `docs/data-model.md` và truy vấn dashboard (`analytics/infrastructure/repositories/analytics_scope.py`).

| Quy tắc | Case |
| --- | --- |
| Doanh thu thuần = tổng hóa đơn bán + `sales_return` (âm) trong cùng khoảng đóng-mở | rev_001, rev_003, growth_009, boundary_015, empty_011 |
| Doanh thu theo khách nhóm theo `customer_id`, gồm cả nhập trả | cust_004, cust_010 |
| Doanh thu sản phẩm/danh mục = dòng bán - dòng trả, grain `product_name + unit_name`, không theo `unit_price` | prod_005, prod_014, cat_020 |
| "Đã bán bao nhiêu" = số lượng bán thuần (bán - trả); không cộng số lượng khác đơn vị tính | prod_006, prod_021 |
| Doanh thu của các hóa đơn có mặt hàng X = `SUM(invoice_total_amount)` các hóa đơn đó (`EXISTS`) + nhập trả `sales_return` cùng kỳ của chính các khách sở hữu hóa đơn (không lọc trả theo mặt hàng, không trừ trả của khách khác) | rev_007 |
| Số dư công nợ có dấu (opening, sale, receipt, sales_return); phải thu = tổng số dư dương từng khách | debt_008, debt_016 |
| Opening/receipt không phải doanh thu | empty_011 |
| Địa bàn dùng `customers.ward_name` hiện tại, không dùng snapshot trên hóa đơn | geo_017, geo_018 |
| Mã hóa đơn người dùng thấy là `invoice_number` | inv_019 |
| Ngữ cảnh báo cáo: giữ `customer_id`/kỳ đã chọn; tên khách tham chiếu không phải bộ lọc | ctx_022, ctx_023 |
| Bình quân hóa đơn = `AVG(invoice_total_amount)`; đếm `customer_id` khác nhau; soft-delete | avg_012, cust_013, inv_002 |
| Lịch sử công nợ: số dư sau từng giao dịch/cuối tháng là lũy kế toàn sổ (mang theo số dư trước ngày bắt đầu), thứ tự `occurred_at` rồi opening → sale → sales_return → receipt như trang `/customers/:id` | debthist_024, debthist_025 |
| Tuổi nợ/nợ cũ theo FIFO đến ngày tính: mọi khoản giảm (kể cả sau mốc) trả khoản tăng cũ nhất trước; không dùng số dư tại mốc | debtage_026 |

Fixture cố ý chứa:

- Biên thời gian `00:00:00` và `23:59:59`.
- Hóa đơn, dòng hàng, phiếu trả và bút toán bị soft-delete.
- Tổng hóa đơn khác tổng dòng hàng để phát hiện chọn sai grain.
- Cùng sản phẩm bán theo hai đơn vị (`Cát xây dựng`: m3 và xe) và nhiều mức đơn giá.
- Phiếu trả Xi măng trong quý 1 (số lượng thuần khác số lượng bán).
- Số dư đầu kỳ, thu nợ, khách ứng trước (số dư âm), khách không có giao dịch.
- Khách đổi địa bàn: snapshot trên hóa đơn (Phường 9) khác địa bàn hiện tại (Phường 2).
- Số lượng thập phân.

Runner không ghi vào bảng nghiệp vụ thật. Nó tạo `TEMP TABLE` trong một connection riêng, sau đó thực thi SQL ứng viên trong transaction `READ ONLY` với statement timeout.

## Chuẩn bị prediction

Cách nhanh nhất là sinh bằng pipeline thật. Mỗi case đi qua QueryAnalyzer (danh mục khách/danh mục hàng lấy từ fixture, không dùng tên khách thật) → SchemaLinker → SQLService → validator (sửa tối đa 2 vòng nếu bị từ chối, mỗi vòng nhận SQL của vòng trước) → chạy trên fixture, sửa tối đa 2 lần khi DB báo lỗi như `TextToSQLUseCase`. Plan đầu tiên chạy được là prediction. Lệnh này gọi LLM đã cấu hình (khoảng một lượt sinh SQL cho mỗi case mỗi lần chạy); LLM không tất định nên nên chạy nhiều lần:

```powershell
$env:AI_QC_BENCHMARK_DSN = "postgresql://postgres:postgres@localhost:5432/ai_assistant"
.\env\Scripts\python.exe evals\generate_predictions.py --runs 3 --out-dir evals\predictions\agent
```

Hoặc tự xuất SQL thành JSONL, mỗi case một dòng:

```json
{"case_id":"rev_001","sql":"SELECT ..."}
```

Benchmark chấm một SQL cho mỗi câu hỏi. Khi agent sinh nhiều query plans, chọn query đại diện cho kết quả cần đối soát (generator chọn plan đầu tiên chạy được).

## Chạy

Chạy từ thư mục `backend/`. DSN chỉ cần trỏ tới một PostgreSQL mà tài khoản có quyền tạo temporary table:

```powershell
.\env\Scripts\python.exe evals\run_execution_eval.py `
  --predictions evals\predictions\agent\run1.jsonl `
  --report evals\reports\run1.json
```

Để tự kiểm chứng toàn bộ fixture và SQL tham chiếu:

```powershell
.\env\Scripts\python.exe evals\run_execution_eval.py `
  --use-reference `
  --report evals\reports\reference_smoke.json
```

### Cách chấm

- Giá trị số so theo giá trị (`7000.00` = `7000`); case `ordered: false` bỏ qua thứ tự dòng.
- Mặc định chấp nhận **cột thừa và đổi thứ tự cột**: prediction đúng khi một nhóm cột của nó tái tạo chính xác kết quả chuẩn (đủ dòng, đúng cặp giá trị trên từng dòng, đúng thứ tự khi `ordered`). Agent thường trả thêm `ma_khach_hang`, `don_vi_tinh`... theo prompt; dòng thừa, giá trị sai hoặc tách nhóm sai vẫn bị chấm sai. Báo cáo ghi `match` (`reference`, `reference_column_subset`, `accepted_1`...).
- `accepted_results` trong dataset khai báo dạng đáp án tương đương, ví dụ tháng dạng số (`EXTRACT`), ngày đầu tháng (`DATE_TRUNC`) hoặc chuỗi `YYYY-MM`. Giá trị có kiểu ghi bằng `{"$datetime": "2025-01-01T00:00:00"}`.
- `--exact-columns`: yêu cầu đúng số cột và thứ tự cột như SQL tham chiếu (cách chấm cũ).
- `--compare-columns`: yêu cầu thêm alias cột trùng ground truth.

## Diễn giải chỉ số

- `coverage`: tỷ lệ case có prediction.
- `execution_success_rate`: tỷ lệ SQL qua validation và thực thi thành công.
- `execution_result_accuracy`: tỷ lệ kết quả đúng trên **toàn bộ case**; prediction thiếu, SQL lỗi và kết quả sai đều tính là sai.
- Exit code `0`: accuracy 100%; `1`: benchmark chạy xong nhưng chưa đạt 100%; `2`: benchmark/config/ground truth bị lỗi.

Trước khi chấm prediction, runner luôn chạy SQL tham chiếu và đối chiếu với `expected_result` đã khai báo. Nếu một trong hai lệch nhau, benchmark dừng ngay để tránh chấm trên ground truth hỏng.

Khi thêm case: tính tay kết quả từ fixture, chạy `--use-reference`, rồi viết thêm một SQL "bẫy" (cách hiểu sai phổ biến) để chắc case thực sự phân biệt đúng/sai.
