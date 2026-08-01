# Configuration Management

Business Chatbot hỗ trợ nhiều cách để cấu hình ứng dụng:

## 1. File YAML (config/local.yml)

```yaml
# Business Chatbot Configuration
llm:
  openai_api_key: "your-openai-api-key-here"
  model: "gpt-4"

vector_db:
  provider: "milvus"
  host: "localhost"
  port: 19530

# ... other settings
```

## 2. File .env

```bash
# Copy .env.example to .env and fill in your values
OPENAI_API_KEY=your_openai_api_key_here
VECTOR_DB__HOST=localhost
VECTOR_DB__PORT=19530
```

## 3. Environment Variables

```bash
export OPENAI_API_KEY="your-key"
export VECTOR_DB__HOST="localhost"
```

## Ưu tiên cấu hình

1. **Environment Variables** (ưu tiên cao nhất)
2. **.env file** (nếu tồn tại)
3. **YAML config files** (local.yml, development.yml, production.yml)
4. **Default values** (trong Settings class)

## Sử dụng ConfigManager

```python
from config.config_manager import get_settings, config_manager

# Lấy settings
settings = get_settings()

# Reload config
config_manager.reload_config()

# Load config thủ công
config_data = config_manager.load_config()
```

## Cấu trúc Settings

```python
settings.llm.openai_api_key
settings.vector_db.host
settings.database.url
settings.api.port
```