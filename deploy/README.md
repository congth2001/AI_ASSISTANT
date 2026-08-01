# Face Recognition Service - Docker Deployment

This directory contains Docker configuration files for deploying the Face Recognition Service.

## Files

- `Dockerfile` - Main Docker image configuration
- `docker-compose.yml` - Complete service stack with dependencies
- `.dockerignore` - Files to exclude from Docker build context

## Services Included

### Core Services
- **face-recognition-service**: Main FastAPI application
- **mongodb**: MongoDB database for storing face and person data
- **milvus-standalone**: Vector database for face embeddings

### Supporting Services
- **etcd**: Key-value store for Milvus
- **minio**: Object storage for Milvus

## Quick Start

### 1. Build and Run All Services
```bash
cd deploy
docker-compose up -d
```

### 2. Build Only the Face Recognition Service
```bash
cd deploy
docker build -t face-recognition-service .
```

### 3. Run Individual Services
```bash
# Start only databases
docker-compose up -d mongodb milvus-standalone

# Start the face recognition service
docker-compose up -d face-recognition-service
```

## Configuration

### Environment Variables
- `SERVICE_CONFIG`: Path to configuration file (default: config/local.yml)
- `MILVUS_HOST`: Milvus server host (default: milvus-standalone)
- `MILVUS_PORT`: Milvus server port (default: 19530)
- `MONGODB_URL`: MongoDB connection URL (default: mongodb://mongodb:27017)
- `MONGODB_DATABASE`: MongoDB database name (default: ai_assistant_db)

### Volumes
- `../config:/app/config` - Configuration files
- `../models:/app/models` - Face recognition models
- `../logs:/app/logs` - Application logs

## Health Checks

The face recognition service includes health check endpoints:
- `GET /api/v1/face-recognition/health` - Service health status

## Ports

- **8000**: Face Recognition Service API
- **27017**: MongoDB
- **19530**: Milvus
- **9000**: MinIO API
- **9001**: MinIO Console

## Development

### Local Development with Docker
```bash
# Start only databases
docker-compose up -d mongodb milvus-standalone

# Run service locally
python run_service.py
```

### Debug Mode
```bash
# Run with debug logging
docker-compose up face-recognition-service
```

## Troubleshooting

### Check Service Status
```bash
docker-compose ps
```

### View Logs
```bash
# All services
docker-compose logs

# Specific service
docker-compose logs face-recognition-service
```

### Restart Services
```bash
# Restart all
docker-compose restart

# Restart specific service
docker-compose restart face-recognition-service
```

### Clean Up
```bash
# Stop and remove containers
docker-compose down

# Stop and remove containers with volumes
docker-compose down -v
```
