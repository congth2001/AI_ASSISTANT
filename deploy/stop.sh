#!/bin/bash

# Face Recognition Service Stop Script

echo "🛑 Stopping Face Recognition Service..."

# Stop all services
docker-compose down

echo "✅ All services stopped!"

# Optional: Remove volumes (uncomment if you want to clean data)
# echo "🧹 Removing volumes..."
# docker-compose down -v
# echo "✅ Volumes removed!"

echo "🎉 Shutdown complete!"
