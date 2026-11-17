# Hạ tầng local (Docker Compose)

`docker-compose.yml` chỉ dựng các dịch vụ hạ tầng cho backend; FastAPI chạy trực tiếp trên máy bằng `python main.py`, không có service ứng dụng trong compose.

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

`Dockerfile` và `.dockerignore` chưa được compose tham chiếu và chưa có quy trình build image backend. `COPY requirements.txt .` yêu cầu build context là `backend/`, không phải `deploy/`.
