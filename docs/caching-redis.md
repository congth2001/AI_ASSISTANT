# Cache Redis

Redis hiện chỉ cache **câu trả lời chat** của staff/admin. Đối chiếu code ngày 2026-11-17.

| Thành phần | File |
| --- | --- |
| Port | `src/modules/assistant/domain/ports/i_cache_service.py` (`ICacheService`: `get`, `set`, `delete`, `exists`) |
| Adapter | `src/modules/assistant/infrastructure/cache/redis_cache.py` (`RedisCache`) |
| Nơi dùng duy nhất | `src/modules/assistant/application/use_cases/chat_use_case.py` |
| Wiring | provider `cache_service` (Singleton) trong `src/modules/assistant/container.py`, truyền vào `chat_use_case`; alias tại `config/container.py` |
| Config | `CacheSettings` trong `config/settings.py` |

## Cái gì được cache

Cache nằm trước agent graph trong cả `ChatUseCase.execute` (`POST /chat`) và `execute_stream` (`POST /chat/stream`). Giá trị là chuỗi JSON `{"response", "intent", "metadata"}`; `metadata` là toàn bộ metadata của lượt gốc (`trace_id`, `node_metrics`, `citations`, `sql_query`, ...).

- Chỉ ghi cache khi lượt chạy thành công: `ChatUseCase._is_cacheable` bỏ qua câu trả lời làm rõ (`needs_clarification`) và lượt công cụ lỗi (`tool_success is False` hoặc có `tool_error_code`, ví dụ lỗi SQL).
- Cache hit: bỏ qua graph; vẫn lưu cặp tin nhắn user/assistant vào PostgreSQL và cập nhật tiêu đề nếu là tin đầu; `done.metadata` có thêm `cache_hit: true`. Luồng stream phát status `cache` và giả lập streaming bằng cách tách response theo dấu cách.
- Guest (`execute_guest`, `execute_guest_stream`) không đọc/ghi cache.
- Không có cache nào khác trong Redis: analytics, SQL, RAG, embedding và token không dùng `cache_service`.

## Key và TTL

Key (`ChatUseCase._make_cache_key`): `chat:response:<32 ký tự đầu của sha256>`. Chuỗi được băm là JSON (`sort_keys=True`) của:

- `query`: tin nhắn `strip().lower()`
- `conversation_id`, `user_id`
- `history`: `{role, content}` của 5 phần tử đầu (`SearchConfig.HISTORY_WINDOW`) của `conversation.messages`; `ConversationRepository.get_conversation` trả tin nhắn mới nhất trước (tối đa 10 tin), nên đó là 5 tin gần nhất
- `version`: hằng số `6` trong code, tăng khi đổi ngữ nghĩa routing/response để bỏ cache cũ

Vì có `conversation_id` và `user_id`, câu trả lời không dùng chung giữa hội thoại hoặc người dùng. Cùng câu hỏi trong cùng hội thoại chỉ trúng cache khi 5 tin gần nhất giống nhau.

TTL: `_CACHE_TTL = 3600` giây (1 giờ), hằng số trong `chat_use_case.py`, không cấu hình được. `RedisCache.set` dùng `setex` khi `ttl` truthy; `ttl` bằng 0/None sẽ lưu không hết hạn (không có call site nào làm vậy hiện nay). Giá trị được lưu bằng `str(value)`.

## Vô hiệu hóa

Có TTL, `version` và xóa theo tiền tố:

- Sau khi đồng bộ dữ liệu thành công, `sync_business_data.py` và `etl_business/job.py` gọi `cache_service.delete_prefix(CHAT_RESPONSE_CACHE_PREFIX)` (`chat:response:`), nên câu trả lời số liệu cũ không còn được phục vụ. `RedisCache.delete_prefix` dùng `SCAN` (không dùng `KEYS`); nếu Redis lỗi thì chỉ ghi cảnh báo và ETL vẫn thành công, khi đó cache chỉ hết hạn theo TTL (tối đa 1 giờ).
- Xóa/đổi tên hội thoại không xóa key liên quan.
- Muốn bỏ toàn bộ cache cũ ngay mà không chạy ETL: tăng `version` trong `_make_cache_key`, hoặc gọi `delete_prefix`.

## Khi Redis lỗi

Mọi phương thức của `RedisCache` bắt `Exception` và ghi `logger.warning` (module `logging`): `get` trả `None` (coi như miss), `set`/`delete` trả `False`, `exists` trả `False`, `delete_prefix` trả số key đã xóa được. Chat vẫn chạy, chỉ mất cache. Lưu ý:

- Kết nối là lazy (client `redis.asyncio.Redis` không kết nối khi khởi tạo), nên app khởi động được khi Redis tắt.
- Client đặt `socket_connect_timeout=2` và `socket_timeout=2` (giây), nên Redis treo không làm chat chờ lâu.
- `ChatUseCase._get_cached` còn coi JSON hỏng là miss.
- Giá trị `get` trả về là chuỗi (`decode_responses=True`).

## Cấu hình

```yaml
cache:
    provider: redis        # chỉ chấp nhận "redis"
    host: localhost
    port: 6379
    db: 0                  # >= 0
    password:              # SecretStr, tùy chọn
```

Env tương ứng theo quy ước Pydantic Settings của dự án (ví dụ `CACHE__HOST`); xem `config/README.md`. Redis dev chạy trong `deploy/docker-compose.yml` (service `redis`, image `redis:6.0`, volume `redis_data`, có healthcheck `redis-cli ping`). Thay config cần restart process vì `cache_service` là Singleton.

## Giới hạn

- TTL và `version` cố định trong code; không có metric hit/miss ngoài cờ `cache_hit` trong metadata.
- Cache được xóa sau ETL nhưng không invalidate theo Milvus; xem `HYBRID_SEARCH.md` cho việc Milvus cũng không tự cập nhật sau ETL.
- Key chỉ phụ thuộc 5 tin gần nhất; mỗi lượt chat thêm 2 tin nên cache của lượt trước hầu như không được dùng lại trong cùng hội thoại, trừ khi gửi lại cùng câu hỏi mà lịch sử chưa đổi (ví dụ sau khi lượt trước lỗi trước bước lưu).
- Metadata trong cache chứa `trace_id` và `node_metrics` của lượt gốc, nên lượt cache hit lặp lại các giá trị này.
- Lỗi Redis chỉ ở mức `warning`, chưa có metric/cảnh báo.
