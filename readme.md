# Business Chatbot

AI-powered business assistant for data analysis and insights, built with Clean Architecture and SOLID principles. Uses **Milvus** vector database for semantic search and RAG.

## 🚀 Features

- **Conversational AI**: Natural language chat interface for business queries
- **Data Analysis**: Automated insights from business data (revenue, profit, customers)
- **Hybrid RAG (Retrieval-Augmented Generation)**: Context-aware responses using both vector similarity and keyword search
- **Multi-Provider LLM Support**: OpenAI GPT and Anthropic Claude integration
- **Milvus Vector Database**: High-performance vector similarity search
- **Clean Architecture**: Domain-driven design with clear separation of concerns
- **SOLID Principles**: Maintainable and extensible codebase
- **Customizable Search**: Fine-tune vector/keyword weights for different query types

## 🔍 Retrieval Methods

### Vector Search (Semantic)
- Finds conceptually similar content
- Uses embeddings and similarity distance
- Fast with indexing

### Keyword Search (BM25-like)
- Finds exact phrase matches
- Term frequency based scoring
- Good for specific metrics and names

### Hybrid Search (RECOMMENDED) ⭐
- Combines vector + keyword search
- Configurable weights (default: 70% vector, 30% keyword)
- Best accuracy for business queries
- Learn more: [Hybrid Search Documentation](docs/HYBRID_SEARCH.md)

## 🏗️ Architecture

### Clean Architecture Layers

```
src/
├── domain/                      # Domain Layer (Business Rules)
│   ├── entities/               # Business Entities
│   ├── value_objects/          # Value Objects
│   ├── interfaces/             # Repository & Service Interfaces
│   └── services/               # Domain Services
├── application/                # Application Layer (Use Cases)
│   ├── use_cases/             # Application Use Cases
│   ├── services/              # Application Services
│   └── dto/                   # Data Transfer Objects
├── infrastructure/             # Infrastructure Layer (External Concerns)
│   ├── llm/                   # LLM Implementations
│   ├── vector_db/             # Milvus Vector Database Implementation
│   ├── persistence/           # Database Implementations
│   ├── embedding/             # Embedding Service Implementations
│   └── cache/                 # Cache Implementations
└── presentation/               # Presentation Layer (API)
    ├── api/                   # FastAPI Routes
    ├── dependencies.py        # Dependency Injection
    └── schemas/               # Pydantic Schemas
```

### SOLID Principles

- **Single Responsibility**: Each class has one reason to change
- **Open/Closed**: Open for extension, closed for modification
- **Liskov Substitution**: Subtypes are substitutable for their base types
- **Interface Segregation**: Clients depend only on methods they use
- **Dependency Inversion**: Depend on abstractions, not concretions

## 📡 API Endpoints

### Chat APIs
- `POST /api/v1/chat` - Send chat message and get AI response
- `GET /api/v1/chat/{conversation_id}` - Get conversation history

### Data APIs
- `POST /api/v1/data/ingest` - Ingest business data
- `POST /api/v1/data/batch` - Batch ingest multiple records

### Reports APIs
- `GET /api/v1/reports` - Query business reports with date range
- `POST /api/v1/reports/custom` - Generate custom reports

## 🛠️ Quick Start

### Prerequisites
- Python 3.11+
- OpenAI API key
- PostgreSQL (optional, uses SQLite by default)
- Redis (optional, for caching)

### 1. Clone and Install
```bash
git clone <repository-url>
cd business-chatbot

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Setup
Create `.env` file:
```bash
# Required
OPENAI_API_KEY=your_openai_api_key_here

# Optional (defaults provided)
LLM__MODEL=gpt-4
VECTOR_DB__PROVIDER=milvus
VECTOR_DB__HOST=localhost
VECTOR_DB__PORT=19530
VECTOR_DB__VECTOR_DIMENSION=512
DATABASE__URL=sqlite+aiosqlite:///./business_chatbot.db
CACHE__HOST=localhost
CACHE__PORT=6379
```

### 3. Run with Docker (Recommended)
```bash
cd deploy
docker-compose up -d
```

### 4. Or Run Locally
```bash
# Seed sample data (optional)
python scripts/seed_database.py

# Run the application
python main.py
```

## 📊 Usage Examples

### Chat with the Bot
```bash
curl -X POST "http://localhost:8000/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What were our total sales last month?",
    "conversation_id": "conv_123"
  }'
```

### Ingest Business Data
```bash
curl -X POST "http://localhost:8000/api/v1/data/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "data_type": "revenue",
    "value": 15000.00,
    "date": "2024-01-15",
    "category": "sales",
    "metadata": {"source": "api"}
  }'
```

### Query Reports
```bash
curl "http://localhost:8000/api/v1/reports?start_date=2024-01-01&end_date=2024-01-31&query=monthly+revenue"
```

## 🔧 Configuration

### Settings Structure
```python
# config/settings.py
class Settings(BaseSettings):
    llm: LLMSettings
    vector_db: VectorDBSettings
    embedding: EmbeddingSettings
    database: DatabaseSettings
    cache: CacheSettings
    api: APISettings
```

### Environment Variables
- `LLM__OPENAI_API_KEY`: OpenAI API key
- `LLM__ANTHROPIC_API_KEY`: Anthropic API key (optional)
- `VECTOR_DB__HOST`: Milvus host (default: localhost)
- `VECTOR_DB__PORT`: Milvus port (default: 19530)
- `VECTOR_DB__COLLECTION_NAME`: Milvus collection name
- `VECTOR_DB__VECTOR_DIMENSION`: Vector dimension (default: 512)
- `DATABASE__URL`: Database connection URL
- `CACHE__HOST`: Redis host
- `CACHE__PORT`: Redis port

## 📁 Project Structure

```
business-chatbot/
├── src/                        # Source code
│   ├── domain/                 # Business domain
│   ├── application/            # Use cases & services
│   ├── infrastructure/         # External integrations
│   └── presentation/           # API & interfaces
├── config/                     # Configuration
│   ├── settings.py            # Pydantic settings
│   └── container.py           # Dependency injection
├── scripts/                    # Utility scripts
│   ├── ingest_data.py         # Data ingestion
│   └── seed_database.py       # Database seeding
├── deploy/                     # Deployment files
│   ├── Dockerfile
│   └── docker-compose.yml
├── data/                       # Data directory
├── logs/                       # Log files
├── main.py                     # Application entry point
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

## 🧪 Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html
```

## 📈 Data Ingestion

### CSV Data
```bash
python scripts/ingest_data.py --csv data/revenue.csv --data-type revenue
```

### Knowledge Base
```bash
python scripts/ingest_data.py --knowledge-base docs/
```

## 🔍 Monitoring

- Health check: `GET /health`
- API documentation: `GET /docs`
- Alternative docs: `GET /redoc`

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

### 1. Tạo Person
```python
import requests

response = requests.post(
    "http://localhost:8000/api/v1/face-recognition/persons/",
    json={
        "name": "John Doe",
        "description": "Test person"
    }
)
person_id = response.json()["data"]["id"]
```

### 2. Đăng ký Khuôn mặt
```python
with open("person_photo.jpg", "rb") as f:
    response = requests.post(
        f"http://localhost:8000/api/v1/face-recognition/faces/upload/register",
        files={"file": f},
        data={"person_id": person_id}
    )
```

### 3. Tìm kiếm Khuôn mặt
```python
with open("query_photo.jpg", "rb") as f:
    response = requests.post(
        "http://localhost:8000/api/v1/face-recognition/faces/upload/search",
        files={"file": f},
        data={
            "threshold": 0.6,
            "max_results": 10
        }
    )
    
matches = response.json()["data"]["matches"]
for match in matches:
    print(f"Person: {match['person_name']}, Similarity: {match['similarity_score']}")
```

## 🧪 Testing

```bash
# Chạy tests
pytest tests/

# Chạy tests với coverage
pytest --cov=services.ai_assistant tests/
```

## 🚀 Deployment

### Docker
```bash
# Build image
docker build -t face-recognition-service .

# Run container
docker run -p 8000:8000 face-recognition-service
```

### Docker Compose
```bash
docker-compose -f docker-compose.face-recognition.yml up -d
```

## 📈 Performance

### Milvus Configuration
- **Index Type**: IVF_FLAT
- **Metric Type**: L2 (Euclidean Distance)
- **Vector Dimension**: 512
- **Collection Shards**: 2

## 🔒 Security

- User authentication và authorization
- Input validation cho tất cả APIs
- File upload security
- Rate limiting cho APIs

## 📝 Logging

```python
import logging

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
```

## 🤝 Contributing

1. Fork repository
2. Tạo feature branch
3. Commit changes
4. Push to branch
5. Tạo Pull Request

## 📄 License

MIT License