# Quản lý lỗi

`common/errors` định nghĩa nhóm lỗi dùng chung, thuần Python. Mỗi lỗi có `error_type` để phân loại, `code` ổn định và `message` được render từ `message_template`.

| Lớp chung | error_type | HTTP |
| --- | --- | --- |
| `NotFoundError` | `not_found` | 404 |
| `PermissionDeniedError` | `not_permission` | 403 |
| `UnauthorizedError` | `unauthorized` | 401 |
| `ValidationError` | `validation` | 400 |
| `RequestValidationError` | `invalid_request` | 422 |
| `ConflictError` | `conflict` | 409 |
| `RateLimitedError` | `rate_limited` | 429 (kèm header `Retry-After`) |
| `ConfigurationError` | `configuration` | 500 |
| `OperationTimeoutError` | `timeout` | 504 |
| `ExternalServiceError` | `external_service` | 502 |
| `InternalError` | `internal` | 500 |

Lỗi cụ thể thuộc catalog `src/modules/<module>/domain/errors.py`. Khai báo code và thông điệp tại đó; nơi phát sinh lỗi chỉ khởi tạo lớp lỗi bằng tham số có tên:

```python
# modules/sales/domain/errors.py
from src.common.errors import ValidationError

class RequiredColumnValueError(ValidationError):
    code = "required_column_value"
    message_template = "Column {column!r} contains an empty value"

# application hoặc infrastructure của sales
raise RequiredColumnValueError(column=column)
```

Không tự viết message, code hoặc `HTTPException(detail=...)` tại router, use case hay adapter. Lỗi trả dưới dạng kết quả (pipeline SQL, SSE) cũng lấy message/code từ catalog. Không đưa chi tiết exception của adapter hoặc secret vào thông báo gửi client; giữ nguyên nhân bằng `raise ... from exc` khi chuyển lỗi.

Domain không phụ thuộc FastAPI/Pydantic hoặc hạ tầng. HTTP mapping nằm tại `src/common/presentation/error_handlers.py`, đăng ký một lần trong `main.py`; response giữ dạng `{"detail": "..."}`. Lỗi 5xx của `ApplicationError` được log phía server; exception không lường trước trả `{"detail": "internal_error"}` (500) và được log kèm stack trace. Sau khi bắt đầu stream, lỗi được gửi bằng SSE event `error` với trường `message`.

Các lớp lỗi giữ builtin base cần thiết như `ValueError`, `PermissionError`, `TimeoutError` để tương thích caller cũ. Message tùy ý trong constructor chỉ phục vụ tương thích; code module phải dùng template. Test `test_error_catalogs.py` kiểm tra quy tắc khai báo, code duy nhất, tham số template và HTTP/SSE contract.
