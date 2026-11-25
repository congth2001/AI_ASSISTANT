# Configuration Management

Pydantic Settings là đầu mối parse, merge và validate cấu hình. `settings.py` định nghĩa schema/validation và source precedence; `config_manager.py` chọn YAML, cache settings và cung cấp facade cho app/CLI/ETL/Alembic. `container.py` chỉ kết nối dependency.

Lỗi cấu hình dùng `ConfigurationError` từ `src.common.errors`, cùng lớp gốc `ApplicationError` với các lỗi được khai báo trong module. Thông điệp cấu hình được làm sạch trước khi tạo lỗi và không chứa giá trị secret.

## Thứ tự ưu tiên

Theo từng trường, kể cả trường trong object lồng nhau:

1. Biến môi trường của tiến trình.
2. File `backend/.env` nếu tồn tại, đọc bằng dotenv source của Pydantic.
3. Một file YAML đã chọn, đọc bằng `YamlConfigSettingsSource`.
4. Default trong schema.

YAML được chọn bằng argument `ConfigManager(config_path=...)`, sau đó đến biến môi trường tiến trình `AI_ASSISTANT_CONFIG_FILE`. Khi không chọn, local development dùng duy nhất `backend/config/local.yml` nếu có. Không dò tìm `development.yml` hoặc `production.yml`. Nếu không có YAML mặc định, có thể chạy hoàn toàn bằng env/.env; file được chọn rõ ràng nhưng không tồn tại luôn gây lỗi.

Đường dẫn tương đối của config/env file tính từ thư mục backend, không phụ thuộc working directory. `AI_ASSISTANT_CONFIG_FILE` phải được đặt trong môi trường tiến trình, không dùng giá trị bên trong `.env` để chọn YAML.

```powershell
$env:AI_ASSISTANT_CONFIG_FILE = "config/production.yml"
.\env\Scripts\python.exe main.py
```

Đổi tên field env bằng dấu `__`, không dùng `OPENAI_API_KEY` đơn lẻ:

```dotenv
LLM__OPENAI_API_KEY="your-real-api-key"
AUTH__JWT_SECRET="your-own-random-secret-with-at-least-32-characters"
DATABASE__HOST=localhost
DATABASE__PORT=5432
DATABASE__PASSWORD="001234 # part of password"
API__DEBUG=false
API__CORS_ORIGINS=["https://example.com","http://localhost:5173"]
```

Danh sách/object dùng JSON trong biến môi trường. Chuỗi như mật khẩu `001234` giữ nguyên; không có bước tự ép mọi giá trị thành int/float. Các biến không thuộc schema trong `.env` được bỏ qua; field lồng nhau sai tên và key YAML không nhận diện sẽ bị từ chối. Biến cũ `PUBLIC_FRONTEND_ORIGINS` (danh sách phân tách bằng dấu phẩy) vẫn được `main.py` đọc từ môi trường tiến trình để tương thích; cách mới là `api.public_frontend_origins` (YAML hoặc `API__PUBLIC_FRONTEND_ORIGINS='["https://app.example.com"]'`). Cả `api.cors_origins` và origin public được chuẩn hóa/validate (dạng `http(s)://host[:port]`) và từ chối `*`.

## Cấu hình API, rate limit và auth bổ sung

- `api.host` mặc định `127.0.0.1` (chỉ máy local); đặt `0.0.0.0` khi cần truy cập từ xa.
- `api.docs_enabled` (mặc định `true`) bật/tắt `/docs`, `/redoc`, `/openapi.json`; nên tắt khi public.
- `rate_limit.*`: giới hạn cửa sổ trượt trong bộ nhớ cho `/auth/login` (theo IP và theo email), `/auth/guest`, `/auth/refresh`; trả `429` kèm `Retry-After`. Mỗi process có bộ đếm riêng và restart sẽ xóa bộ đếm. `trust_forwarded_for` chỉ bật khi chạy sau đúng một reverse proxy tin cậy (ngrok/Cloudflare), khi đó IP lấy từ mục ngoài cùng bên phải của `X-Forwarded-For`; nếu không bật, mọi client sau proxy dùng chung một bucket IP.
- `auth.refresh_reuse_grace_seconds` (mặc định `30`): dùng lại refresh token đã bị xoay vòng quá khoảng này sẽ thu hồi toàn bộ refresh token của user và trả `401`; trong khoảng này (nhiều tab refresh cùng lúc bằng cùng một token) chỉ trả `401` cho request đến sau. Đặt `0` để phát hiện replay nghiêm ngặt. Logout xóa hẳn token nên token đã logout bị gửi lại chỉ nhận `401`, không thu hồi các phiên khác.
- `auth.guest_token_minutes` (mặc định `60`): thời hạn access token của phiên guest stateless (không có refresh token, không ghi bảng `users`).
- `database.sql_reader_role` (mặc định `sales_sql_reader`): role NOLOGIN chỉ có quyền SELECT trên 6 bảng bán hàng, do migration `a91c3e7d5b20` tạo và cấp cho user chạy Alembic. `PostgresSQLExecutor` chạy SQL do LLM sinh sau `SET LOCAL ROLE`. Nếu app kết nối bằng user khác user chạy migration thì cần `GRANT sales_sql_reader TO <app_user>`. Để trống thì tắt (không khuyến nghị; backend log cảnh báo).
- `database.username` không còn mặc định theo tên cá nhân (mặc định `postgres`); `DatabaseSettings.url` và `Settings.to_container_config()` chứa secret rõ, không log/in chúng.

## Cấu hình bắt buộc và secrets

Backend cần `llm.openai_api_key` không rỗng và `auth.jwt_secret` riêng, tối thiểu 32 ký tự. Không còn JWT secret mặc định; hai giá trị mẫu cũ bị từ chối. Thời hạn token, port, token budget, vector dimension và provider được validate trước khi tạo kết nối. Provider hợp lệ hiện là Milvus/OpenAI/Redis tương ứng với adapter đang được wiring.

Có thể copy `.env.example` ở thư mục backend sang `.env`, sau đó nhập secret thật. Hoặc điền YAML, hoặc inject env từ môi trường triển khai. Tạo JWT secret ngẫu nhiên trên máy của bạn:

```powershell
.\env\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

API key, JWT secret, mật khẩu DB/Redis/MDB được giữ dưới dạng `SecretStr`: repr/model_dump_json che giá trị. Lỗi validation của ConfigManager không in input secret. Chỉ `settings.to_container_config()` giải mã secret để truyền cho adapter; không log kết quả của phương thức này hoặc `settings.database.url`.

Không commit `.env`, YAML thật, API key hoặc mật khẩu. Không thay secret của môi trường đang chạy bằng secret từ ví dụ.

## Database dùng chung cho app và Alembic

Có thể cấu hình bằng các field `database.host/port/username/password/db_name/query/echo`, hoặc URL:

```dotenv
DATABASE__URL="postgresql+asyncpg://user:encoded-password@localhost:5432/ai_assistant"
```

`DATABASE_URL` cũ vẫn được hỗ trợ ở env/.env và áp dụng cho **cả app lẫn Alembic**. Trong cùng nguồn, `DATABASE__URL` thắng alias `DATABASE_URL`; các field component được cung cấp rõ ràng thắng field tương ứng trong URL. URL được mở thành component trước khi merge, nên env component vẫn có thể override URL trong YAML/.env. Query options của URL ưu tiên cao thay thế query options từ URL thấp hơn.

Mật khẩu trong field `DATABASE__PASSWORD` hoặc YAML được truyền nguyên bản; `URL.create()` xử lý ký tự đặc biệt khi dựng URL. Nếu tự viết một DSN, cần percent-encode thông tin đăng nhập. Chỉ chấp nhận PostgreSQL; driver được chuẩn hóa thành `postgresql+asyncpg`.

Alembic gọi `get_database_settings()` qua cùng source chain. `alembic.ini` không còn chứa DSN riêng; migration không cần LLM key hay JWT secret. Online dùng URL object để tránh lỗi `%` với ConfigParser; offline cũng dùng cùng URL. Không có thay đổi schema trong đợt chỉnh cấu hình này.

```powershell
.\env\Scripts\python.exe -m alembic upgrade head
.\env\Scripts\python.exe -X utf8 -m alembic upgrade head --sql
```

## Sử dụng trong code

```python
from config.config_manager import ConfigManager, get_settings, get_database_settings

settings = get_settings()
container.config.from_dict(settings.to_container_config())

database = get_database_settings()  # không cần các config LLM/auth
engine = create_async_engine(database.sqlalchemy_url)

custom = ConfigManager("config/production.yml", env_file=".env").get_settings()
```

`get_settings()` cache model đã validate. `reload_config()` xóa cả cache app lẫn database và validate lại. Các DI singleton/kết nối đã tạo không được thay nóng: restart process sau khi đổi config hoặc secret.

`llm.temperature` và `llm.max_tokens` được validate nhưng adapter hiện vẫn có token budget riêng trong các lời gọi OpenAI; thay đổi luồng cấu hình này không thay token policy của adapter.

## Kiểm tra

```powershell
.\env\Scripts\python.exe -m pytest tests/unit/test_configuration.py
.\env\Scripts\python.exe -m pytest tests/unit tests/integrate etl_business/tests
```

Test dùng YAML/.env/secret giả, không cần dịch vụ ngoài hoặc file `local.yml` thật. API test dùng settings tổng hợp riêng để không phụ thuộc secret trên máy lập trình viên.
