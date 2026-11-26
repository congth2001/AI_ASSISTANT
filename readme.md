# AI_ASSISTANT Backend

FastAPI backend cho chatbot phân tích dữ liệu bán hàng bằng tiếng Việt và dashboard kinh doanh. Code tổ chức theo **modular monolith**, giữ **Clean Architecture trong từng module**. PostgreSQL lưu dữ liệu nghiệp vụ/xác thực/hội thoại, Milvus tìm kiếm vector, Redis cache kết quả chat.

## Module

| Module | Trách nhiệm |
| --- | --- |
| src/modules/auth | Guest session, đăng nhập, JWT/refresh/logout, tạo staff/admin |
| src/modules/conversations | Lưu hội thoại/tin nhắn, quyền đọc và ownership khi sửa |
| src/modules/assistant | SSE chat, LangGraph, intent/entity, Text-to-SQL, RAG/hybrid, LLM/cache/vector adapters |
| src/modules/analytics | Dashboard, bộ lọc, khách hàng/công nợ, đơn hàng và xuất Excel |
| src/modules/sales | Repository khách hàng, hóa đơn/dòng hàng, trả hàng, sổ công nợ và đồng bộ dữ liệu |
| src/common | PostgreSQL/session factory, ORM Base, thời gian Việt Nam và lỗi dùng chung |

Mỗi module có domain, application, infrastructure, presentation khi cần và container.py riêng. config/container.py chỉ ghép module và dependency dùng chung; src/bootstrap/router.py tập hợp router module, prefix/tag và endpoint public; main.py wire/mount router tổng. Chi tiết ranh giới dependency, bản đồ file, ORM và cách thêm module nằm trong [ARCHITECTURE.md](ARCHITECTURE.md).

Các interface dịch vụ nằm trong domain/ports/, repository contract nằm trong domain/repositories/. Prompt LLM thuộc assistant/application/prompts/. Các kiểu dữ liệu analytics nằm trong analytics/domain/models/, chia thành dashboard, overview, customer_debt, orders và order_ledger.

Các nhóm lỗi dùng chung nằm trong `src/common/errors/`: `not_found`, `not_permission`, `unauthorized`, `validation`, `conflict`, cấu hình, timeout và lỗi dịch vụ/nội bộ. Mỗi module gom mã lỗi và mẫu thông điệp riêng trong `domain/errors.py`; ánh xạ HTTP status nằm tại `src/common/presentation/error_handlers.py`, giữ response `{"detail": ...}` và contract SSE. Xem `src/common/errors/README.md`.

## Chạy local

Yêu cầu Python 3.11+, môi trường ảo đã cài requirements.txt và Docker cho hạ tầng. Công cụ phát triển/kiểm thử (pytest, black, isort, mypy, flake8, aiosqlite) nằm ở requirements-dev.txt (`pip install -r requirements-dev.txt`, đã gồm requirements.txt). Tên file này giữ chữ thường `readme.md` vì nhiều tài liệu/script đang tham chiếu. Chạy các lệnh từ backend/ vì config loader và Alembic dùng đường dẫn tương đối.

```powershell
Copy-Item config\local.example config\local.yml
# Điền API key, JWT secret và thông tin kết nối trong local.yml.
docker compose --project-name ai_assistant -f deploy\docker-compose.yml up -d
.\env\Scripts\python.exe -m alembic upgrade head
.\env\Scripts\python.exe create_admin.py --email admin@example.com --name "Admin"
.\env\Scripts\python.exe sync_business_data.py   # thêm --allow-shrink chỉ khi cố ý xóa mềm dữ liệu vắng mặt trong snapshot rỗng/giảm >30%
.\env\Scripts\python.exe main.py
```

create_admin.py hỏi mật khẩu qua prompt. Không ghi mật khẩu/API key/token vào command line hoặc commit config/local.yml, .env hay dữ liệu khách hàng. sync_business_data.py đọc năm snapshot trong data/documents/ (Khach_hang.xlsx, Hang_hoa.xlsx, Cong_no.xlsx, Tra_hang.xlsx, Chi_tiet_tra_hang.xlsx) và đồng bộ idempotent; run_business_etl.py chạy trọn chuỗi trích xuất MDB/ZIP → chuẩn hóa → snapshot → đồng bộ, xem [etl_business/README.md](etl_business/README.md). Giữ project name ai_assistant cho Docker Compose; bỏ tham số này sẽ tạo project deploy với volume PostgreSQL trống. local.example để trống LLM API key và JWT secret: điền vào local.yml hoặc đặt LLM__OPENAI_API_KEY, AUTH__JWT_SECRET.

Mặc định API tại http://localhost:8000, Swagger tại /docs, health tại /health. Có thể thêm origin frontend public qua biến PUBLIC_FRONTEND_ORIGINS (phân tách bằng dấu phẩy). Pydantic Settings áp dụng precedence: environment → backend/.env → YAML được chọn → defaults. Chọn YAML bằng AI_ASSISTANT_CONFIG_FILE hoặc argument ConfigManager; local mặc định là config/local.yml nếu có, không dò các file môi trường khác. LLM API key và JWT secret riêng là bắt buộc. App, CLI, ETL và Alembic dùng chung nguồn database; xem [config/README.md](config/README.md).

## API và nghiệp vụ

Endpoint nghiệp vụ dùng prefix /api/v1:

- /auth/*: guest, login, refresh, logout, me, staff.
- /chat và /chat/stream: câu trả lời đầy đủ hoặc SSE; /search-documents cho staff/admin.
- /conversations và /conversations/{id}: quản lý lịch sử cho staff/admin.
- /analytics/*: summary, time-series, time-series-comparison, data-freshness, overview-insights, rankings, filter-options, customer-overview, orders và xuất workbook công nợ/nhật ký.

Swagger là contract API thực tế. Guest chỉ chat stateless, không truy cập business tools. Admin có thể đọc hội thoại của mọi người nhưng chỉ chat/rename/delete hội thoại do mình sở hữu. SSE giữ event data: <json> theo từng khối kết thúc bằng hai newline.

Assistant phân loại conversation/text_to_sql/rag/hybrid; agent có assess, clarify và evaluate_context. Chỉ POST /chat có bước đánh giá câu trả lời và sinh lại khi thiếu citation; node replan đã bị xóa. Text-to-SQL kiểm tra SQL trước khi chạy trong transaction chỉ đọc, timeout 15 giây; validator chỉ cho phép đọc 6 bảng bán hàng (`ALLOWED_SQL_TABLES` trong `sql_service.py`) và từ chối mọi tên bảng không thuộc dữ liệu bán hàng ở bất kỳ vị trí nào (`RESTRICTED_SQL_TABLES`). Khi thêm bảng ORM mới, `tests/unit/test_sql_table_allowlist.py` buộc phân loại bảng vào một trong hai tập. RAG/hybrid search mô tả tại [docs/HYBRID_SEARCH.md](docs/HYBRID_SEARCH.md). OpenAI là adapter được DI cấu hình; Anthropic adapter (AsyncAnthropic) có trong module assistant nhưng cần wiring riêng nếu đổi provider.

Luồng agent, các sửa lỗi ngữ cảnh dashboard và giới hạn xác minh phân tích kinh doanh được mô tả tại [docs/agent-business-analysis.md](docs/agent-business-analysis.md); topology graph tại [docs/agent-graph.md](docs/agent-graph.md).

Analytics dùng Decimal/numeric cho tiền. Công nợ chuẩn lấy từ signed ledger customer_debt_transactions; không cộng debt_delta_amount của hóa đơn để thay số dư sổ. Schema do Alembic quản lý, head e7b3c5a19f42; startup không tạo bảng tự động.

## Kiểm tra

```powershell
.\env\Scripts\python.exe -m pytest tests/unit tests/integrate etl_business/tests
.\env\Scripts\python.exe -m alembic heads
```

Bộ test gồm các kiểm tra ranh giới module, DI/metadata, xác thực/phân quyền, agent/SQL và analytics/workbook. Test hoặc benchmark có dịch vụ ngoài có thể cần config/hạ tầng tương ứng.

Benchmark SQL với PostgreSQL fixture, chạy từ backend/:

```powershell
$env:AI_QC_BENCHMARK_DSN = "postgresql://postgres:postgres@localhost:5432/ai_assistant"
.\env\Scripts\python.exe evals\run_execution_eval.py --use-reference
```

Import Python nội bộ dùng src.modules.<module>.* hoặc src.common.*; không có shim cho các package layer toàn cục cũ. Provider của pipeline SQL trong assistant dùng tên text_to_sql_use_case và sql_executor; các alias CLI/router như auth_use_case, chat_use_case và dashboard_analytics_use_case vẫn được giữ tại config/container.py.

## Tài liệu chuyên đề

- Tổng quan có ba nhóm insight tính xác định, độ mới dữ liệu từ timestamp bản ghi và chuỗi so sánh hai kỳ cùng số ngày: [Tổng quan và insight](../docs/overview-insights.md).
- API analytics: [docs/analytics-api.md](docs/analytics-api.md). Mô hình dữ liệu: [docs/data-model.md](docs/data-model.md).
- Agent graph: [docs/agent-graph.md](docs/agent-graph.md). Cache Redis: [docs/caching-redis.md](docs/caching-redis.md). Nạp dữ liệu Milvus: [docs/milvus-ingestion.md](docs/milvus-ingestion.md). Xác thực: [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md).
- Vận hành: [../docs/runbook-van-hanh.md](../docs/runbook-van-hanh.md). Quy trình đóng góp: [../CONTRIBUTING.md](../CONTRIBUTING.md).
