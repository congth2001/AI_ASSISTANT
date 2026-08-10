# Small Text-to-SQL Execution Benchmark

Bộ benchmark nhỏ gồm 15 câu hỏi có ground truth xác định trên một PostgreSQL fixture cô lập. Mục tiêu chính là đo:

```text
execution result accuracy = số case có kết quả SQL đúng / tổng số case
```

## Thành phần

- `datasets/business_sql_small.jsonl`: câu hỏi, SQL tham chiếu, kết quả chuẩn và quy tắc nghiệp vụ.
- `fixtures/business_sql_small.sql`: dữ liệu tổng hợp cố định, chỉ tạo bảng tạm trong session benchmark.
- `predictions/example_predictions.jsonl`: contract đầu vào mẫu cho SQL do agent sinh.
- `run_execution_eval.py`: kiểm chứng ground truth, kiểm tra an toàn, chạy SQL và xuất báo cáo.

Fixture cố ý chứa:

- Biên thời gian `00:00:00` và `23:59:59`.
- Hóa đơn và dòng hàng bị soft-delete.
- Tổng hóa đơn khác tổng dòng hàng để phát hiện chọn sai grain.
- Công nợ âm, NULL và khách hàng không có hóa đơn.
- Số lượng thập phân.

Runner không ghi vào bảng nghiệp vụ thật. Nó tạo `TEMP TABLE` trong một connection riêng, sau đó thực thi SQL ứng viên trong transaction `READ ONLY` với statement timeout.

## Chuẩn bị prediction

Xuất SQL từ `metadata.sql_queries` của `TextToSQLTool` thành JSONL, mỗi case một dòng:

```json
{"case_id":"rev_001","sql":"SELECT ..."}
```

Benchmark hiện chấm một SQL cho mỗi câu hỏi. Khi agent sinh nhiều query plans, hãy ghép chúng thành một câu `WITH ... SELECT ...` có một result set hoặc chọn query đại diện cho kết quả cần đối soát.

## Chạy

Chạy từ thư mục `backend/`. DSN chỉ cần trỏ tới một PostgreSQL mà tài khoản có quyền tạo temporary table:

```powershell
$env:AI_QC_BENCHMARK_DSN = "postgresql://postgres:postgres@localhost:5432/ai_assistant"
.\env\Scripts\python.exe evals\run_execution_eval.py `
  --predictions evals\predictions\example_predictions.jsonl `
  --report evals\reports\business_sql_small.json
```

File prediction mẫu chỉ có 2/15 case nhằm minh họa cách đo coverage. Để tự kiểm chứng toàn bộ fixture và SQL tham chiếu:

```powershell
.\env\Scripts\python.exe evals\run_execution_eval.py `
  --use-reference `
  --report evals\reports\reference_smoke.json
```

Mặc định alias cột không ảnh hưởng điểm. Thêm `--compare-columns` nếu muốn chấm cả contract tên cột:

```powershell
.\env\Scripts\python.exe evals\run_execution_eval.py `
  --predictions evals\predictions\agent_predictions.jsonl `
  --compare-columns
```

## Diễn giải chỉ số

- `coverage`: tỷ lệ case có prediction.
- `execution_success_rate`: tỷ lệ SQL qua validation và thực thi thành công.
- `execution_result_accuracy`: tỷ lệ kết quả đúng trên **toàn bộ 15 case**; prediction thiếu, SQL lỗi và kết quả sai đều tính là sai.
- Exit code `0`: accuracy 100%; `1`: benchmark chạy xong nhưng chưa đạt 100%; `2`: benchmark/config/ground truth bị lỗi.

Trước khi chấm prediction, runner luôn chạy SQL tham chiếu và đối chiếu với `expected_result` đã khai báo. Nếu một trong hai lệch nhau, benchmark dừng ngay để tránh chấm trên ground truth hỏng.

