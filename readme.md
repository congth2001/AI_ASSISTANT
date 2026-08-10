# Business Chatbot — LLM-to-SQL & RAG Assistant

AI assistant cho phân tích dữ liệu kinh doanh, xây dựng theo **Clean Architecture** với **Agent Graph** (LangGraph). Hệ thống tự động định tuyến câu hỏi sang pipeline phù hợp: truy vấn SQL có cấu trúc hoặc tìm kiếm vector (RAG).

---

## Tính năng

- **Agent Graph (LangGraph)**: Tự động phân tích intent → chọn tool → sinh response
- **Text-to-SQL**: Chuyển câu hỏi tiếng Việt thành SQL, thực thi trên SQLite
- **Hybrid RAG**: Kết hợp vector search (Milvus) + keyword search để tìm tài liệu liên quan
- **Fuzzy Entity Matching**: Nhận dạng tên khách hàng, sản phẩm, danh mục với RapidFuzz
- **Multi-Provider LLM**: OpenAI GPT và Anthropic Claude
- **Conversation Memory**: Lưu lịch sử hội thoại trên PostgreSQL/SQLite

---

## Kiến trúc

### Sơ đồ layers

```
┌─────────────────────────────────────────────┐
│              Presentation Layer              │
│          FastAPI  ·  REST API v1             │
└──────────────────────┬──────────────────────┘
                       │
┌──────────────────────▼──────────────────────┐
│              Application Layer               │
│    ChatUseCase  ·  SearchDocumentsUseCase    │
│    AnalyticsUseCase  ·  IngestDataUseCase    │
└──────────────────────┬──────────────────────┘
                       │ delegates to
┌──────────────────────▼──────────────────────┐
│                 Agent Layer                  │
│                                             │
│  AgentService                               │
│  ┌─────────────────────────────────────┐   │
│  │           LangGraph Graph           │   │
│  │  analyze_query                      │   │
│  │      ├─[needs_analytics]──► text_to_sql ──[has_data]──► generate_response │
│  │      │                    └─[empty]───► rag_tool ──►┐  │
│  │      └─[rag]──────────────► rag_tool ───────────────►┤  │
│  │                                              generate_response → END │
│  └─────────────────────────────────────┘   │
│                                             │
│  Tools: TextToSQLTool · RAGTool             │
└──────────────────────┬──────────────────────┘
                       │ uses
┌──────────────────────▼──────────────────────┐
│               Domain Layer                   │
│  Entities · Value Objects · Interfaces       │
└──────────────────────┬──────────────────────┘
                       │ implemented by
┌──────────────────────▼──────────────────────┐
│            Infrastructure Layer              │
│  OpenAI · Milvus · SQLite · Redis · Pg       │
└─────────────────────────────────────────────┘
```

### Luồng xử lý câu hỏi

```
User message
    ↓
[analyze_query]  — QueryAnalyzer: intent, entity, time extraction (rule-based + fuzzy)
    ↓
[route]  — needs_analytics?
    ├── YES → [execute_text_to_sql]  — SchemaLinker → SQLGenerator (LLM) → SQLValidator → Execute
    │              └── no data? → [execute_rag]
    └── NO  → [execute_rag]          — Milvus search → ContextBuilder
                    ↓
          [generate_response]  — LLM (OpenAI/Claude) + context
                    ↓
              Response to user
```

### Cấu trúc thư mục

```
src/
├── application/                 # Application Layer
│   ├── agent/                   # Agent sub-layer
│   │   ├── agent_service.py     # Public interface cho ChatUseCase
│   │   ├── graph/
│   │   │   ├── state.py         # AgentState (TypedDict)
│   │   │   ├── nodes.py         # Node factories: analyze, text_to_sql, rag, respond
│   │   │   ├── edges.py         # Routing: route_after_analysis, route_after_text_to_sql
│   │   │   └── builder.py       # build_agent_graph() → CompiledGraph
│   │   └── tools/
│   │       ├── base.py          # BaseTool ABC
│   │       ├── text_to_sql.py   # Wrap AnalyticsUseCase (SQL pipeline)
│   │       └── rag_tool.py      # Wrap SearchDocumentsUseCase + ContextBuilder
│   ├── use_cases/
│   │   ├── chat_use_case.py     # Conversation management + delegate to AgentService
│   │   ├── analytics_use_case.py# SQL pipeline: schema link → generate → validate → execute
│   │   ├── search_document_use_case.py
│   │   └── ingest_data_use_case.py
│   └── services/
│       ├── query_analyzer.py    # 9-step rule-based query analysis
│       ├── schema_linker.py     # Map entities → DB schema
│       ├── sql_generator.py     # LLM → SQLQueryPlan[]
│       ├── sql_validator.py     # Safety check (blocklist + EXPLAIN)
│       ├── context_builder.py   # Build context dict for LLM
│       ├── rag_orchestrator.py  # Vector/hybrid search orchestration
│       └── serialization_factory.py
│
├── domain/                      # Domain Layer
│   ├── entities/                # AnalyzedQuery, Message, Conversation, ...
│   ├── value_objects/           # QueryIntent, DocType, AggregationType, ...
│   └── interfaces/              # ILLMService, ISearchRepository, IVectorDB, ...
│
├── infrastructure/              # Infrastructure Layer
│   ├── llm/                     # openai_adapter.py, anthropic_adapter.py
│   ├── vector_db/               # milvus_adapter.py
│   ├── repositories/            # milvus_search_repository.py, analytics_repository.py
│   ├── persistence/             # SQLAlchemy models, conversation_repository.py
│   ├── embedding/               # openai_embedding.py
│   ├── cache/                   # redis_cache.py
│   ├── serializers/             # transaction, customer, period_summary serializers
│   └── utils/                   # logger, singleton
│
└── presentation/                # Presentation Layer
    ├── api/v1/
    │   ├── chat.py              # POST /api/v1/chat
    │   ├── data.py              # POST /api/v1/data/ingest
    │   └── reports.py           # GET  /api/v1/reports
    └── dto/                     # Request/Response schemas
```

---

## Cài đặt

### Yêu cầu

- Python 3.11+
- OpenAI API key
- Milvus (Docker hoặc Milvus Lite)
- PostgreSQL (production) hoặc SQLite (development)
- Redis (optional, cho caching)

### 1. Clone và cài dependencies

```bash
git clone <repository-url>
cd business-chatbot
pip install -r requirements.txt
```

### 2. Cấu hình môi trường

Tạo file `.env`:

```bash
# LLM
OPENAI_API_KEY=your_openai_api_key_here
LLM__MODEL=gpt-4o-mini

# Vector DB (Milvus)
VECTOR_DB__HOST=localhost
VECTOR_DB__PORT=19530
VECTOR_DB__COLLECTION_NAME=business_docs
VECTOR_DB__VECTOR_DIMENSION=512

# Database
DATABASE__URL=sqlite+aiosqlite:///./business_chatbot.db

# Cache (optional)
CACHE__HOST=localhost
CACHE__PORT=6379
```

### 3. Chạy với Docker (khuyến nghị)

```bash
cd deploy
docker-compose up -d
```

### 4. Chạy local

```bash
# Ingest dữ liệu mẫu
python scripts/ingest_data.py

# Khởi động server
python main.py
```

---

## API

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `POST` | `/api/v1/chat` | Gửi tin nhắn, nhận phản hồi AI |
| `GET`  | `/api/v1/chat/{conversation_id}` | Lấy lịch sử hội thoại |
| `POST` | `/api/v1/data/ingest` | Ingest dữ liệu kinh doanh |
| `GET`  | `/api/v1/reports` | Truy vấn báo cáo theo khoảng thời gian |
| `GET`  | `/health` | Health check |
| `GET`  | `/docs` | Swagger UI |

### Ví dụ

```bash
# Chat
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "Doanh thu tháng 3 của khách hàng Anh Hùng là bao nhiêu?", "conversation_id": "uuid-here"}'

# Response
{
  "conversation_id": "...",
  "response": "Doanh thu tháng 3/2024 của khách hàng Anh Hùng là 125,000,000 VND...",
  "intent": "REVENUE",
  "timestamp": "2024-03-15T10:30:00",
  "metadata": {
    "has_data": true,
    "used_fallback": false,
    "tool_used": "text_to_sql"
  }
}
```

---

## Dữ liệu ingestion

Hệ thống ingest theo 3 lớp tài liệu từ file JSONL trong `data/ingestions/`:

| File | Mô tả | Lớp |
|------|-------|-----|
| `transactions.jsonl` | Từng giao dịch (1 row = 1 doc) | Layer 1 |
| `customers.jsonl` | Hồ sơ tổng hợp theo khách hàng | Layer 2 |
| `period_summaries.jsonl` | Tổng hợp theo tháng/quý | Layer 3 |

```bash
python scripts/ingest_data.py
```

---

## Testing

```bash
# Tất cả tests
pytest

# Với coverage
pytest --cov=src --cov-report=html

# Chỉ unit tests
pytest tests/unit/

# Chỉ integration tests
pytest tests/integrate/
```

---

## Dependency Injection

Toàn bộ dependencies được quản lý trong `config/container.py` bằng `dependency-injector`:

```
Container
├── Infrastructure: llm_service, milvus_client, embedding_service, conversation_repo, ...
├── Application:    query_analyzer, schema_linker, sql_generator, sql_validator, context_builder
├── Application/Agent:  text_to_sql_tool → analytics_use_case
│                       rag_tool         → search_documents_use_case + context_builder
│                       agent_service    → query_analyzer + tools + llm_service
└── Use Cases:      chat_use_case    → agent_service + conversation_repo
```
