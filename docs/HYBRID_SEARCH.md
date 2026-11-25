# Hybrid search (RAG trên Milvus)

Nhánh RAG tìm tài liệu bằng hybrid search: kết quả vector search và keyword search được gộp bằng Reciprocal Rank Fusion (RRF), với chuỗi bộ lọc nới dần khi không có kết quả. Toàn bộ API của `MilvusClient` là **đồng bộ**; `RAGTool` gọi chúng qua `asyncio.to_thread`.

## Luồng gọi

```text
RAGTool.run (agent node execute_rag / execute_hybrid, hoặc POST /search-documents)
  -> SearchDocumentsUseCase.execute_analyzed(AnalyzedQuery)
  -> MilvusSearchRepository.search
       _build_filter_chain       # bộ lọc từ chặt đến lỏng
       _hybrid_search_with_fallback
  -> MilvusClient.hybrid_search  # vector + keyword, gộp RRF
  -> ContextBuilder.build_context # retrieved_text, sources, cảnh báo fallback
```

| Thành phần | File |
| --- | --- |
| Client Milvus, schema, RRF | `src/modules/assistant/infrastructure/database/milvus_client.py` |
| Chuỗi bộ lọc, map kết quả | `src/modules/assistant/infrastructure/repositories/milvus_search_repository.py` |
| Use case, phát hiện fallback | `src/modules/assistant/application/use_cases/search_documents_use_case.py` |
| Top-k và ef theo intent | `src/modules/assistant/domain/constants/search_config.py` |
| Wiring | provider `milvus_client`, `milvus_search_repository`, `search_documents_use_case`, `rag_tool` trong `src/modules/assistant/container.py` |

Kết nối Milvus là lazy: chỉ mở ở thao tác vector đầu tiên, nên luồng SQL/hội thoại không cần Milvus sẵn sàng.

## Schema collection

Tạo tự động nếu chưa có (`MilvusClient._create_collection`), không dùng dynamic field:

| Trường | Kiểu | Ghi chú |
| --- | --- | --- |
| `doc_id` | VARCHAR(128) | Khóa chính |
| `doc_type` | VARCHAR(32) | Dùng lọc theo loại tài liệu |
| `text` | VARCHAR(4096) | Nội dung chunk |
| `embedding` | FLOAT_VECTOR | `dim` = `vector_db.vector_dimension` (default 1024 ở settings và `local.example` — phải khớp model embedding và collection đã tạo) |
| `year`, `month` | INT16, INT8 | Lọc theo thời gian |
| `customer_id` | VARCHAR(128) | Lọc theo khách hàng |
| `co_no` | BOOL | Tài liệu về công nợ |
| `doanh_thu` | DOUBLE | Giá trị tham khảo |

Index: HNSW (`M=16`, `efConstruction=200`), metric lấy từ `vector_db.metric_type` (mặc định **COSINE**) khi tạo collection. Với collection đã tồn tại, `MilvusClient` đọc metric của index `embedding` lúc kết nối và search theo metric đó (log cảnh báo nếu khác config), vì search phải dùng đúng metric đã build index. Đổi dimension hoặc metric cần xóa và tạo lại collection.

## Thuật toán

**Vector search** — `search_similar(query_vector, top_k, filter, search_params)`, `ef` lấy theo intent (`SearchConfig.EF_BY_INTENT`, mặc định 100).

**Keyword search** — `keyword_search(query_text, top_k, filter)` lấy tối đa 1.000 entity khớp `filter`, chấm điểm ngay trong Python:

- Với mỗi từ của câu hỏi có trong `text`: cộng số lần xuất hiện, cộng thêm 5 nếu `text` bắt đầu bằng từ đó.
- Chia cho độ dài `text`, rồi nhân với `1 + tỷ lệ từ khớp`.

**Gộp RRF** — `hybrid_search` lấy `2 × top_k` kết quả mỗi nhánh rồi tính:

```latex
score(d) = \frac{w_v}{60 + rank_v(d)} + \frac{w_k}{60 + rank_k(d)}
```

với `w_v = 0.7`, `w_k = 0.3`, rank bắt đầu từ 1. RRF dựa trên thứ hạng nên không cần chuẩn hóa điểm giữa hai nhánh. Kết quả trả về là dict `{"id", "score", "content", "metadata"}`.

**Chuỗi bộ lọc** — `_build_filter_chain` tạo biểu thức Milvus từ `AnalyzedQuery` (loại tài liệu, `customer_id`, `co_no` khi intent là công nợ, `year`, `month`), rồi bỏ dần điều kiện tháng, thời gian, cuối cùng là không lọc. Dừng ở bộ lọc đầu tiên có kết quả; khi đã nới lọc, `SearchDocumentsUseCase` đánh dấu `used_fallback` và `ContextBuilder` thêm cảnh báo để câu trả lời không coi tài liệu lệch kỳ là số liệu đúng kỳ.

## Nạp dữ liệu

`MilvusIngestionRepository` (provider `milvus_ingestion_repository`) có các thao tác insert/update theo chunk, nhưng repository hiện **chưa có CLI hoặc job nào gọi** để nạp tài liệu. ETL chỉ đồng bộ PostgreSQL; Milvus và cache Redis không tự cập nhật sau ETL.

## Hạn chế

- Keyword search quét tối đa 1.000 entity trong Python mỗi lần gọi, không phải BM25 hay full-text index; chậm và kém chính xác khi collection lớn.
- Lỗi Milvus trong `hybrid_search` / `keyword_search` / `search_similar` ném `VectorStoreQueryError` và chuỗi filter dừng ngay (không lặp qua các filter còn lại); `SearchDocumentsUseCase` trả `results=[]` kèm `error_code="vector_store_query"`. Kết quả rỗng hợp lệ vẫn nới filter như cũ. Bộ lọc theo số phiếu (`so_phieu`) không còn: trường này không có trong schema Milvus, số phiếu tra bằng SQL.
- `keyword_search` vẫn quét tối đa 1000 bản ghi rồi chấm điểm bằng Python và ghi cảnh báo khi chạm trần; BM25 của Milvus cần thêm trường sparse vào schema và index lại nên chưa dùng.
- `POST /search-documents` (staff/admin) trả `doc_id`, `doc_type`, `text`, `score`, `metadata` và cờ `used_fallback`, tiện kiểm tra chất lượng truy xuất.
