# Business Chatbot Assistant - Clean Architecture

## Tổng quan

AI-powered business chatbot cho phân tích dữ liệu kinh doanh và business intelligence, sử dụng **RAG (Retrieval-Augmented Generation)** với hybrid search (vector + keyword). Hỗ trợ đa LLM provider (OpenAI GPT-4, Anthropic Claude).

## Cấu trúc Project

```
AI_ASSISTANT/
├── src/
│   ├── domain/                        # Domain Layer - Pure business logic
│   │   ├── entities/                  # Business entities
│   │   │   ├── business_data.py       # Dữ liệu kinh doanh
│   │   │   ├── message.py             # Tin nhắn hội thoại
│   │   │   ├── report.py              # Báo cáo
│   │   │   ├── constants.py
│   │   │   └── errors.py              # Domain exceptions
│   │   ├── interfaces/                # Abstract interfaces
│   │   │   ├── i_llm_service.py
│   │   │   ├── i_embedding_service.py
│   │   │   ├── i_vector_db.py
│   │   │   ├── i_cache_service.py
│   │   │   ├── i_conversation_repository.py
│   │   │   └── i_data_repository.py
│   │   ├── services/                  # Domain services
│   │   │   ├── context_builder.py     # Xây dựng context cho RAG
│   │   │   └── intent_classifier.py  # Phân loại ý định query
│   │   ├── value_objects/             # Immutable value objects
│   │   │   ├── date_range.py
│   │   │   ├── metric_type.py
│   │   │   └── query_intent.py
│   │   ├── repositories/              # Repository abstractions
│   │   │   └── vector_repository.py
│   │   └── llm_providers/
│   │       └── base_provider.py
│   ├── application/                   # Application Layer - Use cases
│   │   ├── use_cases/
│   │   │   ├── chat_use_case.py       # Xử lý hội thoại
│   │   │   ├── ingest_data_use_case.py
│   │   │   └── query_report_use_case.py
│   │   ├── services/
│   │   │   ├── rag_orchestrator.py    # Điều phối RAG pipeline
│   │   │   ├── query_analyzer.py
│   │   │   └── response_formatter.py
│   │   └── dto/
│   │       ├── chat_request.py
│   │       └── chat_response.py
│   ├── infrastructure/                # Infrastructure Layer
│   │   ├── llm/                       # LLM adapters
│   │   │   ├── openai_adapter.py
│   │   │   └── anthropic_adapter.py
│   │   ├── embedding/
│   │   │   └── openai_embedding_service.py
│   │   ├── vector_db/
│   │   │   └── milvus_adapter.py
│   │   ├── repositories/
│   │   │   └── milvus_vector_repository.py
│   │   ├── persistence/               # SQL repositories
│   │   │   ├── business_data_repository.py
│   │   │   ├── conversation_repository.py
│   │   │   └── models.py              # SQLAlchemy ORM models
│   │   ├── cache/
│   │   │   └── redis_cache.py
│   │   ├── database/
│   │   │   ├── milvus_connection.py
│   │   │   ├── mongo_connection.py
│   │   │   └── postgres_connection.py
│   │   └── utils/
│   │       ├── logger/                # Structured logging
│   │       └── singleton/
│   └── presentation/                  # Presentation Layer
│       ├── api/v1/
│       │   ├── chat.py                # Chat endpoints
│       │   ├── data.py                # Data ingestion endpoints
│       │   └── reports.py             # Report endpoints
│       ├── schemas/
│       │   ├── chat_schema.py
│       │   └── report_schema.py
│       └── dependencies.py            # FastAPI DI wiring
├── config/
│   ├── settings.py                    # Pydantic settings
│   ├── container.py                   # DI container
│   └── config_manager.py
├── scripts/
│   ├── ingest_data.py
│   └── seed_database.py
├── tests/
│   └── unit/
├── deploy/
│   ├── Dockerfile
│   └── docker-compose.yml
├── docs/
│   └── HYBRID_SEARCH.md
├── main.py                            # Application entry point
├── requirements.txt
└── .env.example
```

## Clean Architecture Layers

### 1. Domain Layer (`src/domain/`)

Core business logic hoàn toàn độc lập với framework và infrastructure.

| Component | Mô tả |
|-----------|-------|
| **Entities** | `BusinessData`, `Message`, `Report` — pure Python objects |
| **Interfaces** | Abstract contracts cho LLM, embedding, vector DB, cache, repositories |
| **Domain Services** | `ContextBuilder` (xây dựng RAG context), `IntentClassifier` (phân loại query) |
| **Value Objects** | `DateRange`, `MetricType`, `QueryIntent` — immutable, không có identity |

### 2. Application Layer (`src/application/`)

Điều phối use cases, không chứa business rules.

| Component | Mô tả |
|-----------|-------|
| **ChatUseCase** | Xử lý toàn bộ chat flow |
| **IngestDataUseCase** | Nạp dữ liệu vào vector DB và SQL DB |
| **QueryReportUseCase** | Tạo báo cáo từ dữ liệu kinh doanh |
| **RAGOrchestrator** | Điều phối hybrid search → context → LLM call |
| **DTOs** | `ChatRequest`, `ChatResponse` — data transfer giữa layers |

### 3. Infrastructure Layer (`src/infrastructure/`)

Implementations cụ thể của các interfaces trong Domain.

| Component | Implementation |
|-----------|---------------|
| **LLM** | `OpenAIAdapter` (GPT-4), `AnthropicAdapter` (Claude) |
| **Embedding** | `OpenAIEmbeddingService` |
| **Vector DB** | `MilvusAdapter`, `MilvusVectorRepository` |
| **SQL DB** | SQLAlchemy + PostgreSQL/SQLite |
| **Cache** | `RedisCacheService` |
| **Logging** | Structured logger với decorators và middleware |

### 4. Presentation Layer (`src/presentation/`)

FastAPI routers, schemas, dependency injection.

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/api/v1/chat` | POST | Gửi tin nhắn |
| `/api/v1/chat/{id}` | GET | Lịch sử hội thoại |
| `/api/v1/data/ingest` | POST | Nạp dữ liệu |
| `/api/v1/data/batch` | POST | Batch ingest |
| `/api/v1/reports` | GET | Truy vấn báo cáo |
| `/api/v1/reports/custom` | POST | Tạo báo cáo tùy chỉnh |
| `/health` | GET | Health check |

## Data Flow: Chat Request

```
User Message
    │
    ▼
FastAPI Router (presentation/api/v1/chat.py)
    │
    ▼
ChatUseCase (application/use_cases/)
    │
    ▼
RAGOrchestrator
    ├── EmbeddingService  → tạo query vector
    ├── MilvusAdapter     → vector search (semantic)
    ├── DataRepository    → keyword/metadata filter
    └── Hybrid Merge      → weighted score combination
    │
    ▼
ContextBuilder (domain/services/)
    │  → format retrieved chunks thành prompt context
    ▼
OpenAIAdapter / AnthropicAdapter (infrastructure/llm/)
    │  → LLM API call với context
    ▼
ResponseFormatter (application/services/)
    │
    ▼
ConversationRepository → lưu lịch sử (PostgreSQL)
    │
    ▼
ChatResponse → Client
```

## Dependency Flow

```
Presentation  ──────────────────►  Application  ──────────────►  Domain
     │                                  │                           ▲
     │                                  │                           │
     └──────────►  Infrastructure  ─────┘───────────────────────────┘
                  (implements Domain interfaces)
```

- **Domain**: không phụ thuộc bất kỳ layer nào
- **Application**: chỉ phụ thuộc Domain
- **Infrastructure**: implement interfaces của Domain
- **Presentation**: phụ thuộc Application và Domain

## Technology Stack

### Core
| Thành phần | Công nghệ |
|-----------|-----------|
| Web framework | FastAPI + Uvicorn |
| Data validation | Pydantic v2 |
| DI container | `dependency-injector` |

### AI / LLM
| Thành phần | Công nghệ |
|-----------|-----------|
| LLM providers | OpenAI (GPT-4), Anthropic (Claude) |
| Embeddings | OpenAI Embeddings, sentence-transformers |
| Vector DB | Milvus (pymilvus) |
| Hybrid search | Vector similarity + keyword/metadata filter |

### Storage
| Thành phần | Công nghệ |
|-----------|-----------|
| SQL Database | PostgreSQL (prod), SQLite (dev) |
| ORM | SQLAlchemy 2.0 (async) |
| Vector Database | Milvus Standalone |
| Cache | Redis |

### Infrastructure
| Thành phần | Công nghệ |
|-----------|-----------|
| Container | Docker + Docker Compose |
| Object storage | MinIO |
| Message queue | RabbitMQ |
| Milvus metadata | etcd |

## Docker Compose Services

```yaml
services:
  app          # FastAPI application (port 8000)
  milvus       # Vector database (port 19530)
  attu         # Milvus UI (port 8080)
  etcd         # Milvus metadata store
  minio        # Object storage (ports 9000, 9001)
  rabbitmq     # Message queue (ports 5672, 15672)
```

## Configuration (.env)

```bash
# LLM
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
LLM__MODEL=gpt-4

# Vector DB
VECTOR_DB__HOST=localhost
VECTOR_DB__PORT=19530
VECTOR_DB__COLLECTION_NAME=business_data
VECTOR_DB__VECTOR_DIMENSION=512

# SQL Database
DATABASE__URL=postgresql+asyncpg://user:pass@localhost/db

# Cache
CACHE__HOST=localhost
CACHE__PORT=6379

# API
API__PORT=8000
API__HOST=0.0.0.0
```

## SOLID Principles

| Principle | Áp dụng |
|-----------|---------|
| **S** — Single Responsibility | Mỗi class một trách nhiệm: `RAGOrchestrator` chỉ điều phối RAG, `ContextBuilder` chỉ format context |
| **O** — Open/Closed | Thêm LLM provider mới bằng cách tạo adapter mới, không sửa use case |
| **L** — Liskov Substitution | `OpenAIAdapter` và `AnthropicAdapter` hoán đổi nhau qua `ILLMService` |
| **I** — Interface Segregation | `ILLMService`, `IEmbeddingService`, `IVectorDB` tách biệt rõ ràng |
| **D** — Dependency Inversion | `ChatUseCase` phụ thuộc `ILLMService` (interface), không phải `OpenAIAdapter` |

## Adding New Features

1. **Domain**: Định nghĩa entity và interface mới trong `src/domain/`
2. **Application**: Viết use case trong `src/application/use_cases/`
3. **Infrastructure**: Implement interface trong `src/infrastructure/`
4. **Presentation**: Thêm router trong `src/presentation/api/v1/`
5. **Config**: Wire dependencies trong `config/container.py`

## Testing Strategy

```
tests/
├── unit/           # Test domain entities, value objects, domain services
├── integration/    # Test use cases với real DB (không mock)
└── e2e/            # Test API endpoints
```

- Unit test: domain layer (không cần framework)
- Integration test: use cases với real DB — không mock database
- E2E test: HTTP endpoints via TestClient
