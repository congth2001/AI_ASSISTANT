# Backend image. Build from backend/:  docker build -f deploy/Dockerfile -t ai-assistant-backend .
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user; data/logs are the only writable paths.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/data/documents /app/data/etl /app/logs \
    && chown -R app:app /app/data /app/logs
USER app

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Ho_Chi_Minh \
    # The app binds 127.0.0.1 by default; inside a container it must listen on all interfaces.
    API__HOST=0.0.0.0 \
    API__PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Configuration comes from environment variables and/or a YAML file mounted at runtime
# (AI_ASSISTANT_CONFIG_FILE). Run `python -m alembic upgrade head` as a one-off before starting.
CMD ["python", "main.py"]
