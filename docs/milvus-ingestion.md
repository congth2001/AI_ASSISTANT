# Nạp dữ liệu vào Milvus

Tài liệu này tách rõ **Hiện trạng** (đã kiểm chứng trong code ngày 2026-11-17) và **Đề xuất** (chưa tồn tại). Phần tìm kiếm/hybrid search nằm ở [HYBRID_SEARCH.md](HYBRID_SEARCH.md), không lặp lại ở đây.

# Hiện trạng

## Thành phần

| Thành phần | File |
| --- | --- |
| Port nạp dữ liệu | `src/modules/assistant/domain/repositories/i_ingestion_repository.py` (`IIngestionRepository`) |
| Adapter | `src/modules/assistant/infrastructure/repositories/milvus_ingestion_repository.py` (`MilvusIngestionRepository`) |
| Đơn vị dữ liệu | `src/modules/assistant/domain/entities/document_chunk.py` (`DocumentChunk`: `doc_id`, `text`, `metadata`, `doc_type`) |
| Client Milvus, tạo collection | `src/modules/assistant/infrastructure/database/milvus_client.py` |
| Embedding | `OpenAIEmbedding` (`infrastructure/llm/openai_embedding.py`), `embedding_service` trong container |
| Loại tài liệu | `src/modules/assistant/domain/constants/doc_type.py` (`transaction`, `customer`, `period_summary`, `product`, `category`, `category_period`, `all`) |
| Wiring | provider `milvus_ingestion_repository` trong `src/modules/assistant/container.py`, alias tại `config/container.py` |

## Chưa có đường gọi

Không có CLI, job, use case hay endpoint nào gọi `MilvusIngestionRepository`; chỉ có wiring DI. `sync_business_data.py` (ETL) chỉ ghi PostgreSQL. Không có code nào dựng `DocumentChunk` từ dữ liệu bán hàng; không có chunking nào trong repo ngoài định nghĩa entity. Vì vậy collection `business_data` chỉ có dữ liệu nếu ai đó nạp thủ công. Kết nối Milvus là lazy nên backend vẫn chạy khi collection trống hoặc Milvus tắt; khi đó nhánh RAG chỉ trả về rỗng (xem "Hạn chế" trong HYBRID_SEARCH.md).

## API của `MilvusIngestionRepository`

Hàm `async`, gọi client đồng bộ qua `asyncio.to_thread`.

| Hàm | Hành vi |
| --- | --- |
| `insert(chunks)` | Chia lô 10; mỗi lô gọi `embedder.generate_embeddings(texts)` rồi `client.upsert`. Thực chất là upsert theo khóa chính `doc_id`, nên chạy lại cùng `doc_id` ghi đè bản cũ |
| `update(chunks)` | Chia lô 10; với mỗi chunk truy vấn embedding cũ theo `doc_id` và upsert cả lô với embedding cũ; chunk không có embedding cũ được embed lại |
| `page_existing_ids(doc_type, cursor, page_size)` | Lọc `doc_type == "..."` (bỏ nếu `all`) và `doc_id > "<cursor>"`; trả `(set doc_id, next_cursor)` |
| `get_by_doc_id(doc_id)` | Trả `doc_id`, `doanh_thu`, `co_no` hoặc `None` |
| `get_period_revenue(year, month)` | Lấy `doanh_thu` của `period_summary` theo năm/tháng (phục vụ tính tăng trưởng) |

Mapping dòng ghi: `doc_id`, `doc_type`, `text`, `embedding`, và từ `metadata`: `year` (mặc định 0), `month` (0), `customer_id` (`""`), `co_no` (`False`), `doanh_thu` (`float`, mặc định 0.0). Khóa metadata khác bị bỏ qua vì collection không có dynamic field.

### Điểm cần biết khi dùng (quan sát từ code)

- `MilvusClient.upsert` bắt mọi exception, log lỗi và trả `False`. Repository nay kiểm tra giá trị này và ném `VectorStoreWriteError` (`assistant/domain/errors.py`), nên lô ghi thất bại không còn bị nuốt.
- `MilvusClient.query` vẫn nuốt lỗi và trả `None`; `page_existing_ids` khi đó trả `(set(), None)` giống "không có gì". `update` coi `None` là "không có embedding cũ" và embed lại, nên kết quả vẫn đúng.
- `page_existing_ids`: truy vấn không có `order_by`, nhưng cursor giả định kết quả sắp theo `doc_id` tăng dần (code chỉ sắp xếp trong từng trang sau khi lấy); phân trang có thể bỏ sót id. Không nên dựa vào nó để đối chiếu đầy đủ (chưa sửa).
- `text` được cắt còn 4096 ký tự (khớp schema) trước khi ghi; muốn giữ đủ nội dung dài thì phải chia chunk trước khi gọi repository.
- `generate_embeddings` chạy qua `asyncio.to_thread` nên không chặn event loop.

Test: `tests/unit/test_milvus_ingestion_and_cache.py`.

## Schema collection

Do `MilvusClient._create_collection` tự tạo khi collection chưa tồn tại (lần truy cập vector đầu tiên). Bảng trường, kiểu và index nằm ở mục "Schema collection" trong [HYBRID_SEARCH.md](HYBRID_SEARCH.md); điểm cần nhớ cho việc nạp: khóa chính `doc_id` VARCHAR(128), `embedding` có `dim = vector_db.vector_dimension`, `year` INT16, `month` INT8.

## Metric COSINE hard-code và dimension

- Index tạo với `metric_type="COSINE"`, HNSW (`M=16`, `efConstruction=200`) cố định trong code; search mặc định cũng dùng COSINE (`search_similar`, `hybrid_search`).
- `vector_db.metric_type` trong config (`L2`/`IP`/`COSINE`, default settings là `L2`, `local.example` là `Cosine`) được truyền vào `MilvusClient` và lưu ở thuộc tính nhưng không dùng khi tạo index hay search. Đặt `L2` trong config không đổi metric thực tế.
- Default `vector_dimension` đã thống nhất là 1024 ở `VectorDBSettings`, `local.example`, `MilvusClient` và `MilvusIngestionRepository`. Collection đã tạo trước đó với dimension khác vẫn giữ dimension cũ; nếu collection cũ là 512 thì phải đặt tường minh `vector_dimension: 512` hoặc tạo lại collection. Dimension của collection đã tạo không tự đổi; vector nạp phải đúng dimension của collection. Cùng giá trị này cũng được truyền cho `OpenAIEmbedding` (`vector_dimension=config.vector_db.vector_dimension`).
- Đổi dimension hoặc metric cần xóa và tạo lại collection (`MilvusClient.drop_collection()` tồn tại nhưng không có caller).

## Cách nạp thủ công an toàn

Chưa có công cụ chính thức. Nếu cần nạp thử, làm theo hướng dưới đây; đây là quy trình tổng hợp từ hành vi code ở trên, chưa có script kiểm chứng trong repo.

1. Dùng môi trường dev, cấu hình đúng `vector_db.*` và `embedding.*`; xác nhận `vector_dimension` khớp collection (nếu collection đã có, kiểm tra bằng Attu từ `deploy/docker-compose.yml` hoặc `MilvusClient.get_collection_stats()`).
2. Dựng danh sách `DocumentChunk` với `doc_id` **ổn định và xác định** từ nội dung nguồn (ví dụ gồm loại + khóa nghiệp vụ như `period_summary:2026-03`), `doc_type` thuộc `DocType`, `text` <= 4096 ký tự, `metadata` chỉ gồm các khóa schema (`year`, `month`, `customer_id`, `co_no`, `doanh_thu`). Tiền lấy từ `Decimal` rồi mới chuyển `float` tại bước ghi (repository bắt buộc `float` cho `doanh_thu`).
3. Gọi `await container.milvus_ingestion_repository().insert(chunks)` từ một script chạy trong `backend/` (khởi tạo config bằng `settings.to_container_config()` như `sync_business_data.py`). Vì ghi là upsert theo `doc_id`, chạy lại là idempotent: cùng `doc_id` thì ghi đè, không nhân đôi.
4. Lỗi ghi nay ném `VectorStoreWriteError`, nhưng vẫn nên kiểm tra sau khi nạp: so sánh `get_collection_stats()["num_entities"]` với số chunk, rồi gọi `POST /search-documents` (staff/admin) để thử truy xuất.
5. Cache chat Redis chỉ bị xóa sau ETL PostgreSQL, không bị xóa khi nạp Milvus; xem [caching-redis.md](caching-redis.md).
6. Không chạy trên Milvus production hoặc dùng `drop_collection` khi chưa có bản sao lưu/xác nhận.

# Đề xuất (chưa triển khai)

Các mục dưới đây là gợi ý, không phải hành vi hiện có.

- Thêm CLI (`ingest_documents.py` cạnh `sync_business_data.py`) và một use case ở `assistant/application/use_cases/` dựng `DocumentChunk` từ PostgreSQL (hóa đơn, khách, tổng hợp kỳ), gọi sau ETL; ETL hiện không kích hoạt nạp Milvus.
- Làm cho `MilvusClient.query` ném lỗi thay vì trả `None` để phân biệt "rỗng" với "lỗi"; sửa `page_existing_ids` có thứ tự xác định hoặc dùng iterator của Milvus.
- Chia `text` dài thành nhiều chunk thay vì cắt.
- Đọc `vector_db.metric_type` khi tạo index và search, hoặc xóa trường config này.
- Sau khi nạp Milvus, gọi `delete_prefix` của cache chat để câu trả lời RAG cũ không còn được phục vụ.
- Bổ sung test tích hợp với Milvus thật (hiện chỉ có unit test với client giả).
