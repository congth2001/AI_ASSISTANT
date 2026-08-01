# Face Recognition Service Logger

A comprehensive logging system for the Face Recognition Service with support for multiple log levels, structured logging, performance monitoring, and specialized logging for different operations.

## Features

- **Multiple Log Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Colored Console Output**: Easy-to-read colored logs in terminal
- **File Rotation**: Automatic log file rotation with configurable size limits
- **Structured Logging**: JSON format for machine-readable logs
- **Performance Monitoring**: Built-in performance logging and timing
- **API Request Logging**: Automatic HTTP request/response logging
- **Database Operation Logging**: Specialized logging for database operations
- **Face Operation Logging**: Specialized logging for face recognition operations
- **Decorators**: Easy-to-use decorators for automatic logging
- **Context Managers**: Context managers for operation logging
- **Middleware**: FastAPI middleware for request logging

## Quick Start

```python
from utils.logger import info, error, warning, debug, critical

# Basic logging
info("Service started successfully")
warning("High memory usage detected")
error("Database connection failed")
debug("Processing face image")
critical("System is shutting down")
```

## Advanced Usage

### Using Logger Instances

```python
from utils.logger import get_logger

# Get logger for specific module
logger = get_logger("face_detection")
logger.info("Face detection started")
```

### Logging with Extra Fields

```python
from utils.logger import info

# Log with context
info("User login successful", user_id="12345", ip_address="192.168.1.1")
info("Face detected", face_id="face_67890", confidence=0.95)
```

### Performance Logging

```python
from utils.logger import log_performance
import time

start_time = time.time()
# ... do some work ...
duration = time.time() - start_time

log_performance("face_encoding", duration, 
               face_id="face_12345", 
               vector_size=512)
```

### API Request Logging

```python
from utils.logger import log_api_request

log_api_request(
    method="POST",
    path="/api/v1/faces/register",
    status_code=201,
    duration=0.5,
    user_id="12345"
)
```

### Face Operation Logging

```python
from utils.logger import log_face_operation

log_face_operation(
    operation="face_detection",
    face_id="face_12345",
    person_id="person_67890",
    confidence=0.95
)
```

### Database Operation Logging

```python
from utils.logger import log_database_operation

log_database_operation(
    operation="insert",
    collection="faces",
    duration=0.02,
    records_count=1
)
```

### Exception Logging

```python
from utils.logger import log_exception

try:
    # ... some operation ...
    pass
except Exception as e:
    log_exception("Failed to process face image", e, 
                 image_path="/path/to/image.jpg")
```

## Decorators

### Execution Time Decorator

```python
from utils.logger.decorators import log_execution_time

@log_execution_time("face_encoding_operation")
def encode_face(image_path: str):
    # ... face encoding logic ...
    return encoded_vector
```

### Database Operation Decorator

```python
from utils.logger.decorators import log_database_operation_time

@log_database_operation_time("faces", "insert_face")
def insert_face(face_data: dict):
    # ... database insertion logic ...
    return face_id
```

### API Endpoint Decorator

```python
from utils.logger.decorators import log_api_endpoint

@log_api_endpoint("POST", "/api/v1/faces/register")
def register_face(face_data: dict):
    # ... face registration logic ...
    return {"face_id": "face_12345"}
```

## Context Managers

### Operation Context

```python
from utils.logger.decorators import log_operation_context

with log_operation_context("face_detection", image_path="/path/to/image.jpg"):
    # ... face detection logic ...
    pass
```

### Database Context

```python
from utils.logger.decorators import log_database_context

with log_database_context("faces", "find_by_person_id", person_id="person_123"):
    # ... database query logic ...
    pass
```

## FastAPI Middleware

### Request Logging Middleware

```python
from fastapi import FastAPI
from utils.logger.middleware import LoggingMiddleware

app = FastAPI()
app.add_middleware(LoggingMiddleware)
```

## Configuration

The logger can be configured using environment variables:

```bash
# Log levels
export LOG_CONSOLE_LEVEL=INFO
export LOG_FILE_LEVEL=DEBUG
export LOG_ERROR_LEVEL=ERROR

# File settings
export LOG_MAX_FILE_SIZE=10485760  # 10MB
export LOG_BACKUP_COUNT=5

# Feature toggles
export LOG_ENABLE_PERFORMANCE=true
export LOG_ENABLE_API=true
export LOG_ENABLE_DATABASE=true
export LOG_ENABLE_FACE=true
export LOG_ENABLE_JSON=false
export LOG_ENABLE_COLORS=true
```

## Log Files

The logger creates several log files in the `logs/` directory:

- `ai_assistant.log` - General application logs
- `errors.log` - Error logs only
- `critical_errors.log` - Critical error logs
- `performance.log` - Performance metrics (JSON format)
- `api.log` - API request logs (if enabled)
- `database.log` - Database operation logs (if enabled)
- `face_operations.log` - Face recognition operation logs (if enabled)

## Log Format

### Console Format
```
2024-01-15 10:30:45 | INFO     | ai_assistant_service | Service started successfully
```

### File Format
```
2024-01-15 10:30:45 | INFO     | ai_assistant_service | main:create_app:125 | Service started successfully
```

### JSON Format (Performance Logs)
```json
{
  "timestamp": "2024-01-15T10:30:45.123Z",
  "level": "INFO",
  "logger": "ai_assistant_performance",
  "message": "Performance: face_encoding took 0.150s",
  "operation": "face_encoding",
  "duration_ms": 150.0,
  "face_id": "face_12345"
}
```

## Examples

See `examples.py` for comprehensive usage examples.

## Best Practices

1. **Use appropriate log levels**:
   - DEBUG: Detailed information for debugging
   - INFO: General information about program execution
   - WARNING: Something unexpected happened but the program can continue
   - ERROR: A serious problem occurred
   - CRITICAL: A very serious error occurred

2. **Include context in logs**:
   ```python
   info("User action completed", user_id=user_id, action=action_name)
   ```

3. **Use structured logging for machine processing**:
   ```python
   log_performance("operation_name", duration, extra_field=value)
   ```

4. **Log exceptions with context**:
   ```python
   try:
       # ... operation ...
   except Exception as e:
       log_exception("Operation failed", e, context_field=value)
   ```

5. **Use decorators for automatic logging**:
   ```python
   @log_execution_time("operation_name")
   def my_function():
       # ... function logic ...
   ```

## Troubleshooting

### Logs not appearing
- Check log level configuration
- Verify logs directory permissions
- Check if log files are being created

### Performance issues
- Disable unnecessary log features
- Reduce log level in production
- Check disk space for log files

### Missing context in logs
- Ensure you're passing extra fields to log functions
- Use structured logging methods for complex data
