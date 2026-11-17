# Xác thực

API dùng ba vai trò `guest`, `staff` và `admin`, với access token HS256 có thời hạn ngắn và
refresh token được lưu trong cơ sở dữ liệu, xoay vòng (rotate) sau mỗi lần dùng.

## Thiết lập

Cấu hình một secret riêng (tối thiểu 32 ký tự) trong `config/local.yml`:

```yaml
auth:
  jwt_secret: "replace-with-a-long-random-secret"
  jwt_issuer: business-chatbot
  jwt_audience: business-chatbot-web
  access_token_minutes: 15
  refresh_token_days: 30
```

Chạy migration schema trước khi khởi động API:

```powershell
cd backend
.\env\Scripts\python.exe -m alembic upgrade head
```

Tạo quản trị viên đầu tiên từ thư mục backend:

```powershell
.\env\Scripts\python.exe create_admin.py --email admin@example.com --name "Administrator"
```

Migration chủ ý đặt các giá trị `conversations.user_id` cũ về `NULL`, vì các giá trị đó có
trước khi có danh tính được xác thực. Dữ liệu vẫn nằm trong cơ sở dữ liệu nhưng người dùng đã
xác thực không nhìn thấy.

## Endpoint

- `POST /api/v1/auth/guest` — tạo phiên khách ẩn danh; không cần đăng nhập
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/staff` — chỉ admin; tạo tài khoản staff

Mọi endpoint, trừ `/auth/guest`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/health`
và `/`, đều yêu cầu:

```http
Authorization: Bearer <access_token>
```

Các endpoint hội thoại, tìm tài liệu (`/search-documents`) và toàn bộ `/analytics/*` yêu cầu
thêm vai trò `staff` hoặc `admin`. `/chat` và `/chat/stream` chấp nhận guest thông qua luồng
stateless được mô tả bên dưới.

Refresh token chỉ dùng được một lần. Khi refresh, token cũ bị tiêu thụ và token mới được lưu
trong cùng một transaction; hệ thống trả về một cặp token mới. Nếu một refresh token đã bị
tiêu thụ hoặc thu hồi (kể cả do đăng xuất) bị dùng lại, hệ thống coi là có nguy cơ bị đánh cắp:
thu hồi toàn bộ refresh token còn hiệu lực của người dùng đó và trả `401`
(`auth.refresh_reuse_grace_seconds` cho phép dung sai vài giây khi nhiều tab refresh đồng
thời). Đăng xuất thu hồi refresh token hiện tại.

Mật khẩu dùng bcrypt, giới hạn 72 **byte** (UTF-8) và được hash/verify trong thread riêng để không
chặn event loop. Đăng nhập luôn chạy đúng một lần verify (với hash giả cố định khi không có tài
khoản phù hợp) để thời gian phản hồi không lộ email có tồn tại hay không.

Rate limit (cửa sổ trượt trong bộ nhớ, cấu hình ở `rate_limit.*`, trả `429` + `Retry-After`):
`/auth/login` theo IP (10/phút) và theo email (5/phút), `/auth/guest` theo IP (10/phút),
`/auth/refresh` theo IP (30/phút). Hàm dùng chung: `rate_limit(...)` / `enforce_rate_limit(...)`
trong `src/common/presentation/rate_limit.py`.

Mỗi lần gọi `POST /auth/guest` tạo một người dùng có vai trò `guest` trong cơ sở dữ liệu, không
có email và mật khẩu, để khách có thể giữ một cặp token. Khách không có hội thoại: mỗi tin nhắn
của khách được trả lời độc lập và không có gì được lưu. Endpoint này không yêu cầu xác thực và
bị giới hạn tần suất theo IP, nhưng vẫn thêm một dòng vào `users` cho mỗi lần gọi thành công. Dọn
guest cũ và refresh token hết hạn bằng CLI (mặc định chỉ báo cáo, không xóa):

```powershell
.\env\Scripts\python.exe cleanup_auth_data.py --guest-days 30            # dry-run
.\env\Scripts\python.exe cleanup_auth_data.py --guest-days 30 --apply    # xóa thật
```

Chỉ guest không có hội thoại mới bị xóa; refresh token hết hạn bị xóa, token đã thu hồi được giữ
`--revoked-days` ngày (mặc định 7) để vẫn phát hiện được việc dùng lại. Chỉ staff và admin mới
đăng nhập được. Chủ ý không có đăng ký công khai.

## Ma trận phân quyền chat

| Chức năng | Guest | Staff | Admin |
|---|---:|---:|---:|
| Chat một tin nhắn, stateless | Có | Không | Không |
| Chat theo hội thoại | Không | Có, chỉ của mình | Có, chỉ của mình |
| Tạo hội thoại | Không | Có | Có |
| Đọc lịch sử hội thoại | Không | Chỉ của mình | Của mọi người dùng |
| Đổi tên/xóa hội thoại | Không | Chỉ của mình | Chỉ của mình |
| Truy vấn dữ liệu kinh doanh của cửa hàng qua SQL/RAG | Không | Có | Có |
| Tạo tài khoản staff | Không | Không | Có |

Yêu cầu của guest chạy qua một luồng phản hồi stateless riêng, không truy cập repository, SQL,
RAG, cache hay lịch sử hội thoại. Các truy vấn được phân loại là cần công cụ dữ liệu kinh doanh
trả về HTTP 403 trước khi bắt đầu stream phản hồi.

Admin có quyền đọc toàn cục để kiểm tra, nhưng hội thoại thuộc tài khoản khác hoàn toàn chỉ đọc.
Tiếp tục chat, đổi tên hoặc xóa hội thoại đó trả về HTTP 403.
