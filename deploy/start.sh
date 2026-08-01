#!/bin/bash

# Face Recognition Service Startup Script

set -e

echo "🚀 Starting Face Recognition Service..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose is not installed. Please install docker-compose first."
    exit 1
fi

# Create necessary directories
echo "📁 Creating necessary directories..."
mkdir -p ../models
mkdir -p ../logs
mkdir -p ../config

# Check if config file exists
if [ ! -f "../config/local.yml" ]; then
    echo "⚠️  Config file not found. Creating default config..."
    cat > ../config/local.yml << EOF
mongodb:
  url: mongodb://mongodb:27017
  database: ai_assistant_db

ai_assistant:
  milvus:
    host: milvus-standalone
    port: 19530
    collection_name: face_vectors
  facenet_model_path: /app/models/facenet_keras.h5
  min_face_confidence: 0.9
  similarity_threshold: 0.6
EOF
fi

# Start services
echo "🐳 Starting Docker services..."
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 10

# Check service health
echo "🔍 Checking service health..."
if curl -f http://localhost:8000/api/v1/face-recognition/health > /dev/null 2>&1; then
    echo "✅ Face Recognition Service is running!"
    echo "🌐 API available at: http://localhost:8000"
    echo "📚 API docs at: http://localhost:8000/docs"
    echo "🗄️  MongoDB at: localhost:27017"
    echo "🔍 Milvus at: localhost:19530"
else
    echo "⚠️  Service may still be starting. Check logs with: docker-compose logs face-recognition-service"
fi

echo "🎉 Setup complete!"
