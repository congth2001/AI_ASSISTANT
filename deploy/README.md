# Hạ tầng local (Docker Compose)

`docker-compose.yml` mặc định chỉ dựng các dịch vụ hạ tầng; FastAPI chạy trực tiếp trên máy bằng `python main.py`. Service `backend` (image từ `Dockerfile`) chỉ chạy khi bật profile `app`.

## Dịch vụ

| Service | Image | Cổng host | Vai trò |
| --- | --- | --- | --- |
| `postgres` | postgres:16 | 5432 | Dữ liệu nghiệp vụ, xác thực, hội thoại. User/DB mặc định trong compose: `congvq` / `ai_assistant`, `TZ=Asia/Ho_Chi_Minh` |
| `redis` | redis:6.0 | 6379 | Cache câu trả lời chat (TTL 1 giờ) |
| `milvus-standalone` | milvusdb/milvus:v2.5.5 | 19530, 9091 (health) | Vector search cho RAG |
| `etcd` | quay.io/coreos/etcd:v3.5.15 | — | Metadata của Milvus |
| `minio` | minio/minio | 9000, 9001 (console) | Object storage của Milvus, tài khoản mặc định `minioadmin` |
| `attu` | zilliz/attu | 8080 | Giao diện quản trị Milvus |

Volume: `postgres_data`, `redis_data`, `milvus_data`, `etcd_data`, `minio_data`. Volume `rabbitmq_data` được khai báo nhưng không service nào dùng.

Thông tin kết nối trong `config/local.yml` (hoặc biến môi trường `DATABASE__*`, `CACHE__*`, `VECTOR_DB__*`) phải khớp với compose. Mật khẩu mặc định trong compose chỉ dành cho máy local; đổi trước khi mở cổng ra ngoài.

## Lệnh

Luôn dùng project name `ai_assistant`. Nếu bỏ `--project-name`, Compose đặt tên project theo thư mục (`deploy`) và tạo volume PostgreSQL mới, trống.

```powershell
cd D:\AI_ASSISTANT\backend
docker compose --project-name ai_assistant -f deploy\docker-compose.yml up -d
docker compose --project-name ai_assistant -f deploy\docker-compose.yml ps
docker compose --project-name ai_assistant -f deploy\docker-compose.yml down   # giữ volume
```

Không dùng `down -v` trừ khi chủ động xóa toàn bộ dữ liệu. Sau khi hạ tầng chạy: `alembic upgrade head`, `create_admin.py`, đồng bộ dữ liệu rồi `main.py` (xem [readme.md](../readme.md)). Khi backend báo WinError 1225/10061 dù container healthy, xem mục khôi phục trong [DEPLOY_LOCAL_BACKEND.md](../../DEPLOY_LOCAL_BACKEND.md).

## File khác trong thư mục

## Chạy backend trong container (tùy chọn)

`Dockerfile` build với context `backend/`. Danh sách loại trừ nằm ở `Dockerfile.dockerignore` (BuildKit đọc file này vì nó nằm cạnh Dockerfile; `.dockerignore` trong `deploy/` sẽ bị bỏ qua). Image không chứa `config/*.yml`, `.env`, `data/`, `logs/`, `env/`, `tests/`, `evals/`; process chạy bằng user `app` (uid 10001) và lắng nghe `0.0.0.0:8000`.

```powershell
cd D:\AI_ASSISTANT\backend
docker compose --project-name ai_assistant -f deploy\docker-compose.yml --profile app build backend
docker compose --project-name ai_assistant -f deploy\docker-compose.yml --profile app run --rm backend python -m alembic upgrade head
docker compose --project-name ai_assistant -f deploy\docker-compose.yml --profile app up -d
```

Service `backend` mount `config/local.yml` chỉ đọc (`AI_ASSISTANT_CONFIG_FILE`) và ghi đè host bằng tên service (`DATABASE__HOST=postgres`, `CACHE__HOST=redis`, `VECTOR_DB__HOST=milvus-standalone`). Không chạy đồng thời với `python main.py` trên host vì cùng cổng 8000. Image cài toàn bộ `requirements.txt` nên khá nặng (vài GB). ETL (`run_business_etl.py`) vẫn chạy trên host vì cần file nguồn và `data/`.
